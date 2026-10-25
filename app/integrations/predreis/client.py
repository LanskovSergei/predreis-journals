"""Клиент журналы → Предрейс: сервисный токен, справочники, асинхронная подпись."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal, Protocol

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import UpstreamError

logger = logging.getLogger(__name__)

CatalogEntity = Literal["organizations", "drivers", "vehicles"]
TOKEN_PATH = "/api/v1/service/token"
CATALOG_PATH = "/api/v1/service/catalogs/{entity}"
SIGN_PATH = "/api/v1/service/sign"
TOKEN_LEEWAY_S = 60


@dataclass(frozen=True, slots=True)
class CertInfo:
    """Сведения о сертификате подписанта."""

    serial: str
    subject: str
    valid_from: datetime
    valid_to: datetime


@dataclass(frozen=True, slots=True)
class SignTicket:
    """Ответ на отправку документа на подпись."""

    sign_id: str
    status: str


@dataclass(frozen=True, slots=True)
class SignStatus:
    """Состояние задачи подписи в Предрейсе."""

    external_id: str
    sign_id: str | None
    status: Literal["pending", "signed", "failed"]
    signature: bytes | None = None
    tsp: bytes | None = None
    error: str | None = None
    certificate: CertInfo | None = None
    ocsp_status: str | None = None
    signed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SignResult:
    """Итог подписи, готовый к сохранению (сведения о сертификате могут отсутствовать)."""

    signature: bytes
    tsp: bytes | None
    certificate: CertInfo | None
    ocsp_status: str | None
    signed_at: datetime


class SignGateway(Protocol):
    """Шлюз подписи: реальный — Предрейс, в тестах — заглушка."""

    async def submit(
        self, *, signer_user_id: uuid.UUID, document_type: str, content: bytes, external_id: str
    ) -> SignTicket:
        """Отправляет документ на подпись (мгновенный ответ, подпись — позже)."""

    async def fetch(self, external_ids: Sequence[str]) -> list[SignStatus]:
        """Возвращает состояние задач по нашим идентификаторам."""


def _b64(value: Any) -> bytes | None:
    """Декодирует base64-строку (None и пустое значение — None)."""
    return base64.b64decode(value) if value else None


def _dt(value: Any) -> datetime | None:
    """Разбирает ISO-дату/время из ответа Предрейса."""
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def parse_sign_status(item: dict[str, Any]) -> SignStatus:
    """Разбирает элемент ответа GET /api/v1/service/sign (поля сертификата необязательны)."""
    cert = item.get("certificate") or {}
    certificate = None
    if cert.get("serial") and cert.get("valid_from") and cert.get("valid_to"):
        valid_from, valid_to = _dt(cert["valid_from"]), _dt(cert["valid_to"])
        if valid_from and valid_to:
            certificate = CertInfo(
                str(cert["serial"]), str(cert.get("subject") or ""), valid_from, valid_to
            )
    status = str(item.get("status", "")).lower()
    if status not in ("pending", "signed", "failed"):
        raise UpstreamError(f"Неизвестный статус подписи: {status!r}")
    return SignStatus(
        external_id=str(item.get("external_id", "")),
        sign_id=str(item["id"]) if item.get("id") is not None else None,
        status=status,  # type: ignore[arg-type]
        signature=_b64(item.get("signature_b64")),
        tsp=_b64(item.get("tsp_b64")),
        error=item.get("last_error"),
        certificate=certificate,
        ocsp_status=item.get("ocsp_status"),
        signed_at=_dt(item.get("signed_at")),
    )


def _items(data: Any) -> list[dict[str, Any]]:
    """Достаёт список элементов из ответа: либо сам список, либо поле items/data/results."""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "data", "results"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    raise UpstreamError("Неожиданный формат ответа Предрейса")


class PredreisClient:
    """HTTP-клиент сервисного API Предрейса (client credentials, токен живёт 30 минут)."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        """Создаёт клиент; секрет клиента берётся только из настроек."""
        self._settings = settings
        self._http = http or httpx.AsyncClient(
            base_url=settings.predreis_base_url.rstrip("/"), timeout=settings.predreis_timeout_s
        )
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        """Закрывает HTTP-клиент."""
        await self._http.aclose()

    async def _access_token(self, *, force: bool = False) -> str:
        """Возвращает действующий токен; обновляет его заранее и при принудительной замене."""
        async with self._lock:
            if not force and self._token and time.monotonic() < self._expires_at - TOKEN_LEEWAY_S:
                return self._token
            try:
                resp = await self._http.post(
                    TOKEN_PATH,
                    json={
                        "client_id": self._settings.predreis_client_id,
                        "client_secret": self._settings.predreis_client_secret,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                self._token = str(data["access_token"])
                self._expires_at = time.monotonic() + float(data.get("expires_in", 1800))
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                # В сообщение не попадают тело запроса и секрет.
                logger.warning(
                    "Не удалось получить сервисный токен Предрейса: %s", type(exc).__name__
                )
                raise UpstreamError("Не удалось получить токен Предрейса") from exc
            return self._token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Выполняет запрос с токеном; при 401 один раз обновляет токен и повторяет."""
        for attempt in (1, 2):
            token = await self._access_token(force=attempt == 2)
            try:
                resp = await self._http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code == 401 and attempt == 1:
                    continue
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning("Предрейс %s %s -> %s", method, path, exc.response.status_code)
                raise UpstreamError(
                    f"Предрейс вернул {exc.response.status_code}",
                    details={"body": exc.response.text[:500]},
                ) from exc
            except httpx.HTTPError as exc:
                logger.warning("Предрейс недоступен: %s %s (%s)", method, path, type(exc).__name__)
                raise UpstreamError("Предрейс недоступен") from exc
            return resp.json() if resp.content else None
        raise UpstreamError("Предрейс отклонил токен")  # pragma: no cover

    # --- справочники --------------------------------------------------------------------------
    async def list_catalog(
        self,
        entity: CatalogEntity,
        *,
        changed_after: datetime | None = None,
        limit: int = 500,
        offset: int = 0,
        org_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Страница изменений справочника (сортировка по дате изменения)."""
        params: dict[str, Any] = {"limit": min(limit, 500), "offset": offset}
        if changed_after:
            params["changed_after"] = changed_after.isoformat()
        if org_id:
            params["org_id"] = str(org_id)
        data = await self._request("GET", CATALOG_PATH.format(entity=entity), params=params)
        return _items(data)

    # --- подпись ------------------------------------------------------------------------------
    async def submit(
        self, *, signer_user_id: uuid.UUID, document_type: str, content: bytes, external_id: str
    ) -> SignTicket:
        """Отправляет содержимое на подпись сертификатом указанного специалиста (до 2 МБ)."""
        data = await self._request(
            "POST",
            SIGN_PATH,
            json={
                "signer_user_id": str(signer_user_id),
                "document_type": document_type,
                "content_b64": base64.b64encode(content).decode("ascii"),
                "external_id": external_id,
            },
        )
        if not isinstance(data, dict) or "id" not in data:
            raise UpstreamError("Неожиданный ответ Предрейса на отправку подписи")
        return SignTicket(str(data["id"]), str(data.get("status", "pending")))

    async def fetch(self, external_ids: Sequence[str]) -> list[SignStatus]:
        """Состояния задач подписи пачкой."""
        if not external_ids:
            return []
        data = await self._request(
            "GET", SIGN_PATH, params={"external_ids": ",".join(external_ids)}
        )
        return [parse_sign_status(x) for x in _items(data)]


@lru_cache
def get_predreis_client() -> PredreisClient:
    """Возвращает общий экземпляр клиента Предрейса."""
    return PredreisClient(get_settings())

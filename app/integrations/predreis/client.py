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
from app.core.errors import ForbiddenError, UnauthorizedError, UpstreamError
from app.integrations.predreis.signature import is_placeholder

logger = logging.getLogger(__name__)

CatalogEntity = Literal["organizations", "drivers", "vehicles"]
TOKEN_PATH = "/api/v1/service/token"
CATALOG_PATH = "/api/v1/service/catalogs/{entity}"
SIGN_PATH = "/api/v1/service/sign"
VERIFY_PATH = "/api/v1/service/users/verify"
TOKEN_LEEWAY_S = 60


@dataclass(frozen=True, slots=True)
class CertInfo:
    """Сведения о сертификате подписанта."""

    serial: str
    subject: str
    valid_from: datetime
    valid_to: datetime


@dataclass(frozen=True, slots=True)
class VerifiedUser:
    """Пользователь, чей токен подтвердил Предрейс (ответ `users/verify`)."""

    id: uuid.UUID
    email: str | None
    last_name: str
    first_name: str
    middle_name: str | None
    role: str
    org_id: uuid.UUID | None
    journals_access: bool
    is_active: bool

    @property
    def full_name(self) -> str:
        """ФИО одной строкой."""
        return " ".join(p for p in (self.last_name, self.first_name, self.middle_name) if p)


@dataclass(frozen=True, slots=True)
class UserLogin:
    """Результат входа пользователя в Предрейс."""

    access_token: str
    expires_in: int | None = None


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


def _detail(resp: httpx.Response) -> Any:
    """Текст причины из тела ответа (поле detail), если оно есть."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    return body.get("detail", "") if isinstance(body, dict) else ""


def _b64(value: Any) -> bytes | None:
    """Декодирует base64-строку (None и пустое значение — None); мусор — ошибка интеграции."""
    if not value:
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise UpstreamError("Предрейс вернул подпись в неверном формате") from exc


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
    if status == "signed" and is_placeholder(item.get("signature_b64")):
        # Заглушка не подпись: такой результат нельзя принять за заверение документа.
        return SignStatus(
            external_id=str(item.get("external_id", "")),
            sign_id=str(item["id"]) if item.get("id") is not None else None,
            status="failed",
            error="Предрейс вернул подпись-заглушку (AUTO_SIGNATURE), а не подпись",
        )
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

    # --- пользователи ------------------------------------------------------------------------
    async def user_login(self, email: str, password: str) -> UserLogin:
        """Вход теми же почтой и паролем, что в Предрейсе; возвращает токен пользователя.

        Пароль уходит только в Предрейс и нигде не сохраняется и не логируется.
        """
        try:
            resp = await self._http.post(
                self._settings.predreis_user_login_path,
                json={"email": email, "password": password},
            )
        except httpx.HTTPError as exc:
            logger.warning("Вход в Предрейс не удался: %s", type(exc).__name__)
            raise UpstreamError("Предрейс недоступен") from exc
        if resp.status_code in (400, 401, 403, 422):
            raise UnauthorizedError("Неверная почта или пароль", code="invalid_credentials")
        if resp.status_code >= 400:
            logger.warning("Вход в Предрейс: статус %s", resp.status_code)
            raise UpstreamError(f"Предрейс вернул {resp.status_code}")
        try:
            data = resp.json()
        except ValueError:
            data = {}
        token = (data.get("access_token") if isinstance(data, dict) else None) or resp.cookies.get(
            "access_token"
        )
        if not token:
            raise UpstreamError("Предрейс не вернул токен пользователя")
        expires = data.get("expires_in") if isinstance(data, dict) else None
        return UserLogin(str(token), int(expires) if isinstance(expires, int) else None)

    async def verify_user(self, access_token: str) -> VerifiedUser:
        """Спрашивает у Предрейса, действителен ли токен и открыт ли доступ к журналам.

        403 — доступа к журналам нет; 401 — токен недействителен или учётная запись отключена.
        """
        resp: httpx.Response | None = None
        for attempt in (1, 2):
            service_token = await self._access_token(force=attempt == 2)
            try:
                resp = await self._http.post(
                    VERIFY_PATH,
                    json={"access_token": access_token},
                    headers={"Authorization": f"Bearer {service_token}"},
                )
            except httpx.HTTPError as exc:
                logger.warning("Проверка токена не удалась: %s", type(exc).__name__)
                raise UpstreamError("Предрейс недоступен") from exc
            if resp.status_code == 401 and attempt == 1:
                continue  # возможно, истёк сервисный токен — обновляем и повторяем один раз
            break
        assert resp is not None
        if resp.status_code == 401:
            raise UnauthorizedError("Недействительный токен или учётная запись отключена")
        if resp.status_code == 403:
            detail = str(_detail(resp))
            if "журнал" in detail.lower():
                raise ForbiddenError("Доступ к журналам не предоставлен", code="journals_disabled")
            logger.error("Предрейс отказал сервису в проверке токенов: %s", detail)
            raise UpstreamError("У сервиса нет права проверять токены пользователей")
        if resp.status_code != 200:
            logger.warning("Проверка токена: статус %s", resp.status_code)
            raise UpstreamError(f"Предрейс вернул {resp.status_code}")
        try:
            d = resp.json()
            return VerifiedUser(
                id=uuid.UUID(str(d["id"])),
                email=d.get("email"),
                last_name=str(d.get("last_name") or ""),
                first_name=str(d.get("first_name") or ""),
                middle_name=d.get("middle_name"),
                role=str(d["role"]),
                org_id=uuid.UUID(str(d["org_id"])) if d.get("org_id") else None,
                journals_access=bool(d.get("journals_access")),
                is_active=bool(d.get("is_active", True)),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise UpstreamError("Неожиданный ответ проверки токена") from exc

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

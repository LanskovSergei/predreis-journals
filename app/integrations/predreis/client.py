"""Клиент исходящих вызовов журналы → Предрейс (подпись, справочники, уведомления)."""

from __future__ import annotations

import base64
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.errors import UpstreamError
from app.domain.enums import SignatureKind

logger = logging.getLogger(__name__)


class SignCertificate(BaseModel):
    """Метаданные сертификата, которым выполнена подпись."""

    serial: str
    subject: str
    valid_from: datetime
    valid_to: datetime


class SignResponse(BaseModel):
    """Ответ Предрейса на запрос подписи (контракт: docs/integration-contract.md)."""

    signature_b64: str
    tsp_b64: str | None = None
    certificate: SignCertificate
    ocsp_status: str | None = None
    signed_at: datetime


@dataclass(frozen=True, slots=True)
class SignResult:
    """Результат подписи в удобном для сервисов виде."""

    signature: bytes
    tsp: bytes | None
    cert_serial: str
    cert_subject: str
    cert_valid_from: datetime
    cert_valid_to: datetime
    ocsp_status: str | None
    signed_at: datetime


class Signer(Protocol):
    """Интерфейс подписанта: реальная реализация — Предрейс, в тестах — заглушка."""

    async def sign_detached(
        self,
        *,
        content: bytes,
        filename: str,
        kind: SignatureKind,
        signer_user_id: uuid.UUID | None,
        on_behalf_token: str | None,
    ) -> SignResult:
        """Подписывает содержимое откреплённой подписью."""


class PredreisClient:
    """HTTP-клиент к API интеграции Предрейса."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        """Создаёт клиент с базовым URL и сервисным токеном."""
        self._http = http or httpx.AsyncClient(
            base_url=settings.predreis_base_url.rstrip("/"),
            timeout=settings.predreis_timeout_s,
            headers={"Authorization": f"Bearer {settings.predreis_service_token}"},
        )

    async def aclose(self) -> None:
        """Закрывает HTTP-клиент."""
        await self._http.aclose()

    async def _request(
        self, method: str, path: str, *, headers: dict[str, str] | None = None, **kwargs: Any
    ) -> Any:
        """Выполняет запрос, превращая сетевые ошибки и 4xx/5xx в UpstreamError."""
        try:
            resp = await self._http.request(method, path, headers=headers, **kwargs)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Предрейс %s %s -> %s", method, path, exc.response.status_code)
            raise UpstreamError(
                f"Предрейс вернул {exc.response.status_code}",
                details={"body": exc.response.text[:500]},
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("Предрейс недоступен: %s %s (%s)", method, path, exc)
            raise UpstreamError("Предрейс недоступен") from exc
        return resp.json() if resp.content else None

    async def sign_detached(
        self,
        *,
        content: bytes,
        filename: str,
        kind: SignatureKind,
        signer_user_id: uuid.UUID | None,
        on_behalf_token: str | None,
    ) -> SignResult:
        """Просит Предрейс подписать файл (КриптоПро, ключи — на стороне Предрейса)."""
        headers = {"X-On-Behalf-Of": on_behalf_token} if on_behalf_token else None
        body = {
            "kind": kind.value,
            "signer_user_id": str(signer_user_id) if signer_user_id else None,
            "filename": filename,
            "content_b64": base64.b64encode(content).decode("ascii"),
        }
        data = await self._request("POST", "/integration/v1/sign", json=body, headers=headers)
        resp = SignResponse.model_validate(data)
        return SignResult(
            signature=base64.b64decode(resp.signature_b64),
            tsp=base64.b64decode(resp.tsp_b64) if resp.tsp_b64 else None,
            cert_serial=resp.certificate.serial,
            cert_subject=resp.certificate.subject,
            cert_valid_from=resp.certificate.valid_from,
            cert_valid_to=resp.certificate.valid_to,
            ocsp_status=resp.ocsp_status,
            signed_at=resp.signed_at,
        )

    async def notify(self, event_type: str, payload: dict[str, Any]) -> None:
        """Отправляет в Предрейс уведомление (счётчики, запросы на подпись/удаление)."""
        await self._request(
            "POST", "/integration/v1/notify", json={"event_type": event_type, "payload": payload}
        )

    async def list_changes(
        self, entity: str, *, cursor: str | None = None, limit: int = 200
    ) -> dict[str, Any]:
        """Возвращает страницу изменений справочника: {items: [...], next_cursor: str | None}."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        data = await self._request("GET", f"/integration/v1/{entity}", params=params)
        return dict(data or {"items": [], "next_cursor": None})

    async def list_certificates(self, user_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        """Возвращает статусы сертификатов медиков и механиков (для плашек на стартовой)."""
        params = {"user_id": str(user_id)} if user_id else None
        data = await self._request("GET", "/integration/v1/certificates", params=params)
        return list(data or [])

    async def create_entity(self, entity: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Создаёт сущность в Предрейсе (источник истины) и возвращает её представление."""
        data = await self._request("POST", f"/integration/v1/{entity}", json=payload)
        return dict(data or {})


@lru_cache
def get_predreis_client() -> PredreisClient:
    """Возвращает общий экземпляр клиента Предрейса."""
    return PredreisClient(get_settings())

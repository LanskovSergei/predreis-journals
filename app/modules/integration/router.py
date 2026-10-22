"""Входящий канал событий Предрейс → журналы."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ValidationFailedError
from app.integrations.predreis.schemas import IntegrationEvent
from app.modules.integration.security import verify_request
from app.modules.integration.service import IntegrationService

router = APIRouter(prefix="/integration/v1", tags=["Интеграция (служебное)"])
_event_adapter: TypeAdapter[IntegrationEvent] = TypeAdapter(IntegrationEvent)


@router.post("/events", summary="Приём событий от Предрейса (HMAC)")
async def receive_event(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    """Проверяет подпись, валидирует и применяет событие; повторная доставка безопасна."""
    body = await request.body()
    verify_request(body, request.headers, get_settings())
    try:
        event = _event_adapter.validate_json(body)
    except ValidationError as exc:
        raise ValidationFailedError(
            "Некорректное событие", details=json.loads(exc.json(include_url=False))
        ) from exc
    return {"status": await IntegrationService(session).handle(event)}

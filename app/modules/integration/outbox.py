"""Outbox исходящих уведомлений. У Предрейса пока нет API уведомлений — запись выключена."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.integration import OutboxEvent

logger = logging.getLogger(__name__)


async def enqueue(session: AsyncSession, event_type: str, payload: dict[str, Any]) -> None:
    """Кладёт событие в outbox, если уведомления включены (JOURNALS_PREDREIS_NOTIFY_ENABLED)."""
    if not get_settings().predreis_notify_enabled:
        logger.debug("Уведомления выключены, событие %s не сохранено", event_type)
        return
    session.add(OutboxEvent(event_type=event_type, payload=payload))
    await session.flush()

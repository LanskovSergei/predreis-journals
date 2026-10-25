"""Сообщения очереди, которые не удалось превратить в запись: учёт для оператора."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import InboxFailure

logger = logging.getLogger(__name__)


async def record_failure(
    session: AsyncSession,
    *,
    message_id: str,
    event_type: str | None,
    reason: str,
    detail: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Сохраняет сообщение вместе с причиной, чтобы оно не терялось и не блокировало очередь."""
    logger.warning("Сообщение %s пропущено: %s %s", message_id, reason, detail or "")
    session.add(
        InboxFailure(
            message_id=message_id[:128],
            event_type=event_type,
            reason=reason,
            detail=(detail or "")[:1000] or None,
            payload=payload,
        )
    )
    await session.commit()

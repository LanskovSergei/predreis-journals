"""Outbox: надёжная доставка уведомлений в Предрейс."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UpstreamError
from app.integrations.predreis.client import PredreisClient
from app.models.integration import OutboxEvent

logger = logging.getLogger(__name__)

MAX_BACKOFF_S = 3600


async def enqueue(session: AsyncSession, event_type: str, payload: dict[str, Any]) -> None:
    """Кладёт событие в outbox в рамках текущей транзакции."""
    session.add(OutboxEvent(event_type=event_type, payload=payload))
    await session.flush()


async def dispatch_pending(
    session: AsyncSession, client: PredreisClient, *, batch: int = 50
) -> int:
    """Отправляет накопленные события; при ошибке откладывает попытку с экспоненциальной паузой."""
    now = datetime.now(timezone.utc)
    events = (
        (
            await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.sent_at.is_(None), OutboxEvent.next_attempt_at <= now)
                .order_by(OutboxEvent.created_at)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    sent = 0
    for ev in events:
        try:
            await client.notify(ev.event_type, ev.payload)
        except UpstreamError as exc:
            ev.attempts += 1
            ev.last_error = exc.message[:500]
            delay = min(2**ev.attempts * 5, MAX_BACKOFF_S)
            ev.next_attempt_at = now + timedelta(seconds=delay)
            logger.warning("Outbox %s: попытка %s не удалась", ev.id, ev.attempts)
        else:
            ev.sent_at = datetime.now(timezone.utc)
            sent += 1
    await session.commit()
    return sent

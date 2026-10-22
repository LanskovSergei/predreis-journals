"""Служебные таблицы интеграции с Предрейсом: inbox, outbox, состояние синхронизации."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InboxEvent(Base):
    """Принятое событие от Предрейса. Уникальность event_id обеспечивает идемпотентность."""

    __tablename__ = "inbox_events"

    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(Base):
    """Исходящее уведомление в Предрейс (счётчики, запросы на подпись и удаление)."""

    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class SyncState(Base):
    """Курсор сверки справочников с Предрейсом по каждой сущности."""

    __tablename__ = "sync_state"

    entity: Mapped[str] = mapped_column(String(32), primary_key=True)
    cursor: Mapped[str | None] = mapped_column(String(255))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

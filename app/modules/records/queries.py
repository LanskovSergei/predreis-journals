"""Типизированные выборки записей по виду журнала."""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import JournalKind
from app.models.records import AnyRecord, record_model


async def load_record(
    session: AsyncSession, kind: JournalKind, record_id: uuid.UUID, *, for_update: bool = False
) -> AnyRecord | None:
    """Загружает запись нужного журнала (при необходимости — с блокировкой строки)."""
    model: Any = record_model(kind)
    stmt = select(model).where(model.id == record_id)
    if for_update:
        stmt = stmt.with_for_update()
    return cast("AnyRecord | None", (await session.execute(stmt)).scalar_one_or_none())

"""Фоновые задачи (ARQ): доставка outbox и сверка справочников с Предрейсом."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.integrations.predreis.client import get_predreis_client
from app.integrations.predreis.schemas import (
    DriverPayload,
    OrganizationPayload,
    UserPayload,
    VehiclePayload,
)
from app.models.catalog import Driver, Organization, User, Vehicle
from app.models.integration import SyncState
from app.modules.catalog.service import (
    upsert_driver,
    upsert_organization,
    upsert_user,
    upsert_vehicle,
)
from app.modules.integration.outbox import dispatch_pending

logger = logging.getLogger(__name__)

# Порядок важен: сначала организации и пользователи, затем зависящие от них сущности.
SYNC_PLAN: list[tuple[str, type[BaseModel], Any]] = [
    ("organizations", OrganizationPayload, upsert_organization),
    ("users", UserPayload, upsert_user),
    ("drivers", DriverPayload, upsert_driver),
    ("vehicles", VehiclePayload, upsert_vehicle),
]
_ = (Driver, Organization, User, Vehicle)  # модели нужны Alembic/metadata


async def process_outbox(ctx: dict[str, Any]) -> int:
    """Отправляет накопленные уведомления в Предрейс."""
    async with get_sessionmaker()() as session:
        sent = await dispatch_pending(session, get_predreis_client())
    if sent:
        logger.info("Outbox: отправлено %s событий", sent)
    return sent


async def reconcile_catalog(ctx: dict[str, Any]) -> dict[str, int]:
    """Ночная сверка: подтягивает изменения справочников по курсору и применяет к репликам."""
    client = get_predreis_client()
    counts: dict[str, int] = {}
    async with get_sessionmaker()() as session:
        for entity, payload_cls, upsert in SYNC_PLAN:
            state = (
                await session.execute(select(SyncState).where(SyncState.entity == entity))
            ).scalar_one_or_none()
            if state is None:
                state = SyncState(entity=entity)
                session.add(state)
            cursor = state.cursor
            applied = 0
            while True:
                page = await client.list_changes(entity, cursor=cursor)
                for item in page.get("items", []):
                    await upsert(session, payload_cls.model_validate(item))
                    applied += 1
                cursor = page.get("next_cursor") or cursor
                state.cursor = cursor
                state.synced_at = datetime.now(timezone.utc)
                await session.commit()
                if not page.get("next_cursor"):
                    break
            counts[entity] = applied
    logger.info("Сверка справочников: %s", counts)
    return counts

"""Инкрементальная синхронизация справочников Предрейса (pull по changed_after)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.integrations.predreis.client import CatalogEntity
from app.integrations.predreis.schemas import DriverPayload, OrganizationPayload, VehiclePayload
from app.models.integration import InboxFailure, SyncState
from app.modules.catalog.service import upsert_driver, upsert_organization, upsert_vehicle

logger = logging.getLogger(__name__)

Upsert = Callable[[AsyncSession, Any], Awaitable[None]]

# Порядок важен: водители и ТС ссылаются на организации.
SYNC_PLAN: list[tuple[CatalogEntity, type[BaseModel], Upsert]] = [
    ("organizations", OrganizationPayload, upsert_organization),
    ("drivers", DriverPayload, upsert_driver),
    ("vehicles", VehiclePayload, upsert_vehicle),
]


class CatalogSource(Protocol):
    """Источник справочников (клиент Предрейса или заглушка в тестах)."""

    async def list_catalog(
        self,
        entity: CatalogEntity,
        *,
        changed_after: datetime | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Страница изменений справочника."""


def _parse(value: str | None) -> datetime | None:
    """Разбирает сохранённую отметку синхронизации."""
    return datetime.fromisoformat(value) if value else None


async def sync_entity(
    session: AsyncSession,
    source: CatalogSource,
    entity: CatalogEntity,
    payload_cls: type[BaseModel],
    upsert: Upsert,
    settings: Settings,
) -> int:
    """Забирает изменения одного справочника и применяет их; возвращает число обработанных строк.

    Отметка синхронизации — максимальный `updated_at` из ответа; при следующем запуске она
    сдвигается назад на небольшой запас (повторная обработка безвредна: upsert идемпотентен).
    Некорректные строки и строки с отсутствующей организацией пропускаются и попадают в
    `inbox_failures`, не останавливая синхронизацию.
    """
    state = (
        await session.execute(select(SyncState).where(SyncState.entity == entity))
    ).scalar_one_or_none()
    if state is None:
        state = SyncState(entity=entity)
        session.add(state)
    watermark = _parse(state.cursor)
    since = watermark - timedelta(seconds=settings.catalog_sync_overlap_s) if watermark else None
    newest = watermark
    offset = applied = 0
    while True:
        items = await source.list_catalog(
            entity, changed_after=since, limit=settings.catalog_page_size, offset=offset
        )
        for item in items:
            try:
                payload = payload_cls.model_validate(item)
                async with session.begin_nested():
                    await upsert(session, payload)
            except (ValidationError, IntegrityError) as exc:
                reason = "catalog_invalid" if isinstance(exc, ValidationError) else "catalog_fk"
                session.add(
                    InboxFailure(
                        message_id=str(item.get("id", "?")),
                        event_type=f"catalog.{entity}",
                        reason=reason,
                        detail=str(exc)[:500],
                        payload=item,
                    )
                )
                logger.warning("Справочник %s: строка пропущена (%s)", entity, reason)
                continue
            applied += 1
            changed = getattr(payload, "updated_at", None)
            if changed is not None:
                changed = changed if changed.tzinfo else changed.replace(tzinfo=timezone.utc)
                newest = changed if newest is None or changed > newest else newest
        if len(items) < settings.catalog_page_size:
            break
        offset += len(items)
    if newest is not None:
        state.cursor = newest.isoformat()
    state.synced_at = datetime.now(timezone.utc)
    await session.commit()
    return applied

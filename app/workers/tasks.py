"""Фоновые задачи (ARQ): синхронизация справочников и подпись документов в Предрейсе."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.integrations.predreis.client import get_predreis_client
from app.modules.catalog.sync import SYNC_PLAN, sync_entity
from app.modules.ejournal.service import EJournalService
from app.modules.signing.service import SigningService

logger = logging.getLogger(__name__)


async def sync_catalogs(ctx: dict[str, Any]) -> dict[str, int]:
    """Подтягивает изменения организаций, водителей и ТС из Предрейса."""
    client, settings = get_predreis_client(), get_settings()
    counts: dict[str, int] = {}
    async with get_sessionmaker()() as session:
        for entity, payload_cls, upsert in SYNC_PLAN:
            counts[entity] = await sync_entity(
                session, client, entity, payload_cls, upsert, settings
            )
    if any(counts.values()):
        logger.info("Синхронизация справочников: %s", counts)
    return counts


async def process_sign_jobs(ctx: dict[str, Any]) -> dict[str, int]:
    """Отправляет задачи подписи в Предрейс и завершает готовые (записи и электронные журналы)."""
    client = get_predreis_client()
    async with get_sessionmaker()() as session:
        journals = EJournalService(session, client)
        counts = await SigningService(session, client, journal_finisher=journals).process_jobs()
    if any(counts.values()):
        logger.info("Задачи подписи: %s", counts)
    return counts

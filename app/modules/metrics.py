"""Метрики Prometheus: HTTP-запросы и показатели состояния интеграции из БД.

Доступ по токену `JOURNALS_METRICS_TOKEN` (заголовок `Authorization: Bearer ...`); если токен не
задан, метод отключён (404). Показатели из БД позволяют заметить остановку воркера или
потребителя очереди: растёт «возраст» последней синхронизации и последней обработки события.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import NotFoundError, UnauthorizedError
from app.domain.enums import SignJobStatus
from app.models.documents import EJournal, SignJob
from app.models.integration import InboxEvent, InboxFailure, SyncState

router = APIRouter(tags=["Служебное"], include_in_schema=False)


async def business_metrics(session: AsyncSession) -> bytes:
    """Показатели состояния из БД в формате Prometheus (отдельный реестр на каждый запрос)."""
    now = datetime.now(timezone.utc)
    registry = CollectorRegistry()

    jobs = Gauge("journals_sign_jobs", "Задачи подписи по статусам", ["status"], registry=registry)
    counts = dict(
        (
            await session.execute(select(SignJob.status, func.count()).group_by(SignJob.status))
        ).all()
    )
    for status in SignJobStatus:
        jobs.labels(status.value).set(counts.get(status, 0))
    oldest = (
        await session.execute(
            select(func.min(SignJob.created_at)).where(
                SignJob.status.in_([SignJobStatus.QUEUED, SignJobStatus.PENDING])
            )
        )
    ).scalar_one()
    Gauge(
        "journals_sign_job_oldest_active_age_seconds",
        "Возраст самой старой неоконченной задачи подписи (0, если нет)",
        registry=registry,
    ).set((now - oldest).total_seconds() if oldest else 0)

    failures = Gauge(
        "journals_inbox_failures",
        "Сообщения очереди, не ставшие записями",
        ["reason"],
        registry=registry,
    )
    for reason, count in (
        await session.execute(
            select(InboxFailure.reason, func.count()).group_by(InboxFailure.reason)
        )
    ).all():
        failures.labels(reason).set(count)

    journals = Gauge(
        "journals_ejournals", "Электронные журналы по статусам", ["status"], registry=registry
    )
    for journal_status, count in (
        await session.execute(select(EJournal.status, func.count()).group_by(EJournal.status))
    ).all():
        journals.labels(journal_status.value).set(count)

    last = (await session.execute(select(func.max(InboxEvent.processed_at)))).scalar_one()
    Gauge(
        "journals_inbox_last_processed_age_seconds",
        "Секунд с последней обработки события очереди (нет событий: 0)",
        registry=registry,
    ).set((now - last).total_seconds() if last else 0)

    sync = Gauge(
        "journals_catalog_sync_age_seconds",
        "Секунд с последней синхронизации справочника",
        ["entity"],
        registry=registry,
    )
    for entity, synced in (
        await session.execute(select(SyncState.entity, SyncState.synced_at))
    ).all():
        sync.labels(entity).set((now - synced).total_seconds() if synced else -1)
    return generate_latest(registry)


def _authorize(authorization: str | None = Header(default=None)) -> None:
    """Проверяет токен метрик; без настроенного токена метод скрыт."""
    expected = get_settings().metrics_token
    if not expected:
        raise NotFoundError("Не найдено")
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(given.encode(), expected.encode()):
        raise UnauthorizedError("Неверный токен метрик")


@router.get("/metrics", dependencies=[Depends(_authorize)])
async def metrics(request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    """Метрики Prometheus."""
    body = generate_latest() + await business_metrics(session)
    return Response(body, media_type=CONTENT_TYPE_LATEST)

"""Настройки воркера ARQ."""

from __future__ import annotations

from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.workers.tasks import process_outbox, reconcile_catalog


async def startup(ctx: dict[str, Any]) -> None:
    """Инициализация воркера: логирование."""
    setup_logging(get_settings().log_level)


class WorkerSettings:
    """Конфигурация ARQ: задачи, расписание и подключение к Redis."""

    functions: ClassVar[list[Any]] = [process_outbox, reconcile_catalog]
    cron_jobs: ClassVar[list[Any]] = [
        cron(process_outbox, second={0, 15, 30, 45}),
        cron(reconcile_catalog, hour={3}, minute={0}),
    ]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

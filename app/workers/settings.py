"""Настройки воркера ARQ."""

from __future__ import annotations

from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.workers.tasks import process_sign_jobs, sync_catalogs


async def startup(ctx: dict[str, Any]) -> None:
    """Инициализация воркера: логирование."""
    setup_logging(get_settings().log_level)


class WorkerSettings:
    """Конфигурация ARQ: задачи, расписание и подключение к Redis."""

    functions: ClassVar[list[Any]] = [sync_catalogs, process_sign_jobs]
    cron_jobs: ClassVar[list[Any]] = [
        cron(sync_catalogs, minute=set(range(0, 60, 5)), second={0}, run_at_startup=True),
        # Предрейс подписывает пачками каждые 10 секунд — опрашиваем с тем же шагом.
        cron(process_sign_jobs, second={0, 10, 20, 30, 40, 50}, run_at_startup=True),
    ]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

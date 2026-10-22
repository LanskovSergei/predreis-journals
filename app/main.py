"""Точка входа FastAPI-приложения «Электронные журналы»."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging
from app.integrations.predreis.client import get_predreis_client
from app.modules import health
from app.modules.catalog.router import router as catalog_router
from app.modules.deletion.router import router as deletion_router
from app.modules.ejournal.router import router as ejournal_router
from app.modules.integration.router import router as integration_router
from app.modules.medical.router import router as medical_router
from app.modules.ocr.router import router as ocr_router
from app.modules.reports.router import router as reports_router
from app.modules.stats.router import router as stats_router
from app.modules.technical.router import router as technical_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Освобождает пулы соединений при остановке."""
    yield
    await get_predreis_client().aclose()
    await get_engine().dispose()
    logger.info("Сервис остановлен")


def create_app() -> FastAPI:
    """Собирает приложение: роутеры, CORS, обработчики ошибок."""
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="API электронных журналов предрейсовых осмотров (смежный с Предрейс ONLINE).",
        lifespan=lifespan,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Content-Disposition"],
        )
    register_exception_handlers(app)

    api = APIRouter(prefix="/api/v1")
    for r in (
        stats_router,
        medical_router,
        technical_router,
        deletion_router,
        catalog_router,
        reports_router,
        ejournal_router,
        ocr_router,
    ):
        api.include_router(r)
    app.include_router(api)
    app.include_router(integration_router)
    app.include_router(health.router)
    return app


app = create_app()

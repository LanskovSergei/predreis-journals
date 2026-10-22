"""Технические эндпоинты: liveness и readiness."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session

router = APIRouter(tags=["Служебное"])


@router.get("/health", summary="Liveness")
async def health() -> dict[str, str]:
    """Сервис запущен."""
    return {"status": "ok"}


@router.get("/ready", summary="Readiness (проверка БД)")
async def ready(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    """Сервис готов принимать запросы: есть соединение с БД."""
    await session.execute(text("SELECT 1"))
    return {"status": "ready"}

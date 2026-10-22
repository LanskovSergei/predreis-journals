"""Асинхронное подключение к PostgreSQL."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Создаёт (один раз) асинхронный движок SQLAlchemy."""
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Возвращает фабрику сессий."""
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Зависимость FastAPI: сессия на запрос. Коммит выполняют сервисы явно."""
    async with get_sessionmaker()() as session:
        yield session

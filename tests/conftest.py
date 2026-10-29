"""Общие фикстуры. Интеграционные тесты требуют JOURNALS_TEST_DATABASE_URL (PostgreSQL)."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.storage import LocalStorage
from app.models import Base

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def db_url() -> str:
    """Адрес тестовой БД; применяет миграции один раз за сессию."""
    url = os.environ.get("JOURNALS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Не задан JOURNALS_TEST_DATABASE_URL — интеграционные тесты пропущены")
    env = {**os.environ, "JOURNALS_DATABASE_URL": url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], env=env, cwd=ROOT, check=True
    )
    return url


@pytest_asyncio.fixture
async def session(db_url: str) -> AsyncIterator[AsyncSession]:
    """Чистая сессия БД: перед каждым тестом все таблицы очищаются."""
    engine = create_async_engine(db_url, poolclass=NullPool)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    """Файловое хранилище во временном каталоге."""
    return LocalStorage(tmp_path)

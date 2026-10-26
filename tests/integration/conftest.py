"""Фикстуры интеграционных тестов."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from tests.http_stack import Stack, build_stack


@pytest_asyncio.fixture
async def stack(
    session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Stack]:
    """Приложение с настоящими БД и файлами и подставными Предрейсом и шлюзом подписи."""
    async for item in build_stack(session, tmp_path, monkeypatch):
        yield item

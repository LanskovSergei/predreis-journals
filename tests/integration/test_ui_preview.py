"""Предварительный показ: интерфейс журналов видят только пользователи из JOURNALS_UI_ALLOWED_USERS и СА."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.core.config import get_settings
from tests.http_stack import Stack

pytestmark = pytest.mark.asyncio


@pytest.fixture
def preview(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Список предварительного показа: медик по почте (в другом регистре), механик — нет."""
    monkeypatch.setenv("JOURNALS_UI_ALLOWED_USERS", " Medic@E.ru , someone@example.ru")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def ui(stack: Stack, who: str) -> bool:
    return (await stack.client.get("/api/v1/me", headers=stack.auth(who))).json()["ui_enabled"]


async def test_everyone_sees_journals_when_list_is_empty(stack: Stack) -> None:
    """Список пуст — журналы видны всем, у кого есть доступ (обычный режим)."""
    assert await ui(stack, "medic") and await ui(stack, "mechanic") and await ui(stack, "client")


async def test_only_listed_users_and_superadmin_see_journals(stack: Stack, preview: None) -> None:
    """Список задан — видят только перечисленные (почта без учёта регистра) и суперадмин."""
    assert await ui(stack, "medic") is True
    assert await ui(stack, "mechanic") is False
    assert await ui(stack, "client") is False
    assert await ui(stack, "sa") is True  # суперадмин видит всегда


async def test_listed_by_user_id(stack: Stack, monkeypatch: pytest.MonkeyPatch) -> None:
    """В списке можно указать идентификатор пользователя вместо почты."""
    monkeypatch.setenv("JOURNALS_UI_ALLOWED_USERS", str(stack.world.mechanic.id))
    get_settings.cache_clear()
    try:
        assert await ui(stack, "mechanic") is True and await ui(stack, "medic") is False
    finally:
        get_settings.cache_clear()

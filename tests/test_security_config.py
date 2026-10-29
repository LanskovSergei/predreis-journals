"""Проверка безопасности: настройки CORS, секреты в настройках, разбор XML без внешних сущностей."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.xmlschemas import safe_fromstring

ROOT = Path(__file__).resolve().parents[1]


def test_secrets_are_not_printed_with_settings() -> None:
    """Секрет Предрейса и токен метрик не видны в repr настроек и при выводе в лог."""
    settings = Settings(predreis_client_secret="s3cr3t-value", metrics_token="m3tr1cs-token")
    shown = repr(settings) + str(settings.model_dump())
    assert "s3cr3t-value" not in shown and "m3tr1cs-token" not in shown
    assert settings.predreis_client_secret.get_secret_value() == "s3cr3t-value"


def test_external_entities_are_not_resolved() -> None:
    """XXE: внешняя сущность с путём к файлу не раскрывается."""
    payload = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/hostname">]><x>&e;</x>'
    )
    root = safe_fromstring(payload)
    assert not (root.text or "").strip()


def test_entity_expansion_bomb_is_not_expanded() -> None:
    """«Миллиард смехов»: вложенные сущности не разворачиваются в память."""
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
        b"<l>&c;</l>"
    )
    root = safe_fromstring(bomb)
    assert len(root.text or "") < 100


def test_container_verification_uses_the_safe_parser() -> None:
    """Проверка контейнера (ZIP может прийти извне) не разбирает XML небезопасным способом."""
    source = (ROOT / "app" / "modules" / "ejournal" / "container.py").read_text(encoding="utf-8")
    assert "etree.fromstring(" not in source and "safe_fromstring(" in source


@pytest.mark.asyncio
async def test_cors_allows_the_frontend_without_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    """CORS: разрешён только адрес фронтенда, cookies не разрешены, заголовки — только нужные."""
    from app.main import create_app

    monkeypatch.setenv("JOURNALS_CORS_ORIGINS", '["https://app.example.ru"]')
    get_settings.cache_clear()
    try:
        app = create_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as client:
            ok = await client.options(
                "/api/v1/me",
                headers={
                    "Origin": "https://app.example.ru",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization",
                },
            )
            other = await client.options(
                "/api/v1/me",
                headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
            )
    finally:
        get_settings.cache_clear()
    assert ok.headers["access-control-allow-origin"] == "https://app.example.ru"
    assert "access-control-allow-credentials" not in ok.headers
    assert "authorization" in ok.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-origin" not in other.headers

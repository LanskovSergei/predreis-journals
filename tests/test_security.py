"""Проверка JWT (RS256/JWKS) и HMAC входящих событий."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import security
from app.core.config import Settings, get_settings
from app.core.errors import UnauthorizedError
from app.core.security import JwksCache, decode_token, principal_from_claims
from app.domain.enums import Role
from app.modules.integration.security import sign_body, verify_request

KID = "test-key"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StaticJwks(JwksCache):
    """Кэш JWKS с единственным заранее известным ключом."""

    def __init__(self) -> None:
        """Не обращается к сети."""
        super().__init__("http://unused", 60)

    async def get_key(self, kid: str) -> Any:
        """Возвращает тестовый публичный ключ."""
        if kid != KID:
            raise UnauthorizedError("Неизвестный ключ")
        return KEY.public_key()


def _token(**over: Any) -> str:
    """Выпускает тестовый JWT Предрейса."""
    claims = {
        "sub": str(uuid.uuid4()),
        "role": "medic",
        "journals_access": True,
        "iss": "predreis-online",
        "aud": "journals",
        "exp": int(time.time()) + 300,
        "name": "Тестов Т.Т.",
        **over,
    }
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": KID})


@pytest.fixture
def settings() -> Settings:
    """Настройки с параметрами по умолчанию."""
    return Settings()


async def test_valid_token_decodes(settings: Settings) -> None:
    """Корректный токен проходит проверку и превращается в Principal."""
    token = _token()
    claims = await decode_token(token, settings, StaticJwks())
    principal = principal_from_claims(claims, token, "127.0.0.1")
    assert principal.role is Role.MEDIC
    assert principal.journals_access is True


@pytest.mark.parametrize(
    "over",
    [{"aud": "other"}, {"iss": "evil"}, {"exp": int(time.time()) - 10}],
)
async def test_invalid_claims_rejected(settings: Settings, over: dict[str, Any]) -> None:
    """Чужая аудитория, издатель или просроченный токен отклоняются."""
    with pytest.raises(UnauthorizedError):
        await decode_token(_token(**over), settings, StaticJwks())


async def test_alg_none_rejected(settings: Settings) -> None:
    """Токен без подписи (alg=none) не принимается."""
    forged = jwt.encode(
        {"sub": "x", "iss": "predreis-online", "aud": "journals"},
        None,
        algorithm="none",
        headers={"kid": KID},
    )
    with pytest.raises(UnauthorizedError):
        await decode_token(forged, settings, StaticJwks())


def test_hmac_roundtrip() -> None:
    """Подписанный запрос проходит проверку; подделка, чужое тело и старый запрос — нет."""
    settings = Settings(predreis_hmac_secret="s3cret")
    body = json.dumps({"a": 1}).encode()
    ts = str(int(time.time()))
    good = {"x-timestamp": ts, "x-signature": sign_body("s3cret", ts, body)}
    verify_request(body, good, settings)
    with pytest.raises(UnauthorizedError):
        verify_request(body + b" ", good, settings)
    with pytest.raises(UnauthorizedError):
        verify_request(body, {**good, "x-signature": "0" * 64}, settings)
    old = str(int(time.time()) - 3600)
    with pytest.raises(UnauthorizedError):
        verify_request(
            body, {"x-timestamp": old, "x-signature": sign_body("s3cret", old, body)}, settings
        )


def test_hmac_disabled_without_secret() -> None:
    """Без секрета канал интеграции закрыт."""
    with pytest.raises(UnauthorizedError):
        verify_request(
            b"{}", {"x-timestamp": "1", "x-signature": "x"}, Settings(predreis_hmac_secret="")
        )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[httpx.AsyncClient]:
    """HTTP-клиент поверх ASGI-приложения с подменой JWKS."""
    from app.main import create_app

    monkeypatch.setattr(security, "get_jwks_cache", lambda: StaticJwks())
    get_settings.cache_clear()
    app = create_app()
    yield httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    get_settings.cache_clear()


async def test_api_requires_token(client: httpx.AsyncClient) -> None:
    """Без токена — 401 в едином формате ошибок."""
    resp = await client.get("/api/v1/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


async def test_api_me_and_journals_flag(client: httpx.AsyncClient) -> None:
    """С доступом к журналам /me отдаёт права; без доступа — 403."""
    ok = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {_token()}"})
    assert ok.status_code == 200
    assert "medical:sign" in ok.json()["permissions"]
    denied = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {_token(journals_access=False)}"}
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "journals_disabled"


async def test_events_endpoint_rejects_bad_signature(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Событие с неверной подписью не принимается."""
    monkeypatch.setenv("JOURNALS_PREDREIS_HMAC_SECRET", "s3cret")
    get_settings.cache_clear()
    resp = await client.post(
        "/integration/v1/events",
        content=b"{}",
        headers={"x-timestamp": str(int(time.time())), "x-signature": "deadbeef"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "bad_signature"

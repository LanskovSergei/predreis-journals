"""Вход пользователей: токен проверяет Предрейс, журналы кэшируют ответ и строят права по роли."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.ratelimit import LoginGuard, SlidingWindowLimiter
from app.core.security import UserVerifier, get_user_verifier, parse_role, principal_from_user
from app.domain.enums import Role
from app.integrations.predreis.client import UserLogin, VerifiedUser, get_predreis_client
from app.modules.auth.router import get_login_limiter

USER_ID = uuid.UUID("13a3aa8c-8d2c-4509-8676-9955f8e332d4")
SECRET_PASSWORD = "Sup3r-secret-pass!"


def user(**over: Any) -> VerifiedUser:
    """Ответ users/verify (как в образце Предрейса)."""
    base: dict[str, Any] = {
        "id": USER_ID,
        "email": "user@example.ru",
        "last_name": "Иванов",
        "first_name": "Иван",
        "middle_name": "Иванович",
        "role": "superadmin",
        "org_id": None,
        "journals_access": True,
        "is_active": True,
    }
    return VerifiedUser(**{**base, **over})


class FakePredreis:
    """Подставной клиент Предрейса: токены → пользователи или отказы."""

    def __init__(self) -> None:
        """Таблица токенов и счётчики вызовов."""
        self.tokens: dict[str, VerifiedUser | Exception] = {"good": user()}
        self.verify_calls = 0
        self.login_calls: list[tuple[str, str]] = []
        self.password_ok = True

    async def verify_user(self, token: str) -> VerifiedUser:
        """Проверка токена."""
        self.verify_calls += 1
        result = self.tokens.get(token, UnauthorizedError("Недействительный токен"))
        if isinstance(result, Exception):
            raise result
        return result

    async def user_login(self, email: str, password: str) -> UserLogin:
        """Вход в Предрейс."""
        self.login_calls.append((email, password))
        if not self.password_ok:
            raise UnauthorizedError("Неверная почта или пароль", code="invalid_credentials")
        return UserLogin(access_token="good", expires_in=1800)


class Clock:
    """Управляемое время."""

    def __init__(self) -> None:
        """Начало отсчёта."""
        self.now = 1000.0

    def __call__(self) -> float:
        """Текущее время."""
        return self.now


def make_verifier(fake: FakePredreis, clock: Clock, **settings: Any) -> UserVerifier:
    """Проверяющий с подменой клиента и времени."""
    return UserVerifier(fake, Settings(**settings), clock)  # type: ignore[arg-type]


async def test_success_is_cached_and_expires() -> None:
    """Повторные запросы с тем же токеном не ходят в Предрейс; через TTL проверка повторяется."""
    fake, clock = FakePredreis(), Clock()
    verifier = make_verifier(fake, clock, auth_cache_ttl_s=30)
    for _ in range(5):
        assert (await verifier.verify("good")).id == USER_ID
    assert fake.verify_calls == 1
    clock.now += 31
    await verifier.verify("good")
    assert fake.verify_calls == 2


async def test_access_revocation_takes_effect_after_cache_ttl() -> None:
    """Суперадмин отключил доступ: по истечении TTL кэша пользователь получает отказ."""
    fake, clock = FakePredreis(), Clock()
    verifier = make_verifier(fake, clock, auth_cache_ttl_s=30)
    await verifier.verify("good")
    fake.tokens["good"] = ForbiddenError(
        "Доступ к журналам не предоставлен", code="journals_disabled"
    )
    await verifier.verify("good")  # ещё в кэше
    clock.now += 31
    with pytest.raises(ForbiddenError) as exc:
        await verifier.verify("good")
    assert exc.value.code == "journals_disabled"


async def test_failures_are_cached_only_briefly() -> None:
    """Отказ кэшируется на секунды: защита Предрейса от повторов, но без «залипания»."""
    fake, clock = FakePredreis(), Clock()
    verifier = make_verifier(fake, clock, auth_negative_cache_ttl_s=5)
    for _ in range(3):
        with pytest.raises(UnauthorizedError):
            await verifier.verify("bad")
    assert fake.verify_calls == 1
    clock.now += 6
    with pytest.raises(UnauthorizedError):
        await verifier.verify("bad")
    assert fake.verify_calls == 2


async def test_cache_is_bounded_and_does_not_store_tokens() -> None:
    """Кэш ограничен по размеру; в ключах нет самих токенов."""
    fake, clock = FakePredreis(), Clock()
    verifier = make_verifier(fake, clock, auth_cache_max=10)
    for n in range(50):
        fake.tokens[f"t{n}"] = user()
        await verifier.verify(f"t{n}")
    assert len(verifier._cache) <= 10
    assert all("t1" not in key and len(key) == 64 for key in verifier._cache)


async def test_invalidate_forgets_token() -> None:
    """После invalidate токен проверяется заново."""
    fake, clock = FakePredreis(), Clock()
    verifier = make_verifier(fake, clock)
    await verifier.verify("good")
    verifier.invalidate("good")
    await verifier.verify("good")
    assert fake.verify_calls == 2


@pytest.mark.parametrize(
    ("raw", "role"),
    [
        ("superadmin", Role.SA),
        ("super_admin", Role.SA),
        ("Admin", Role.ADMIN),
        ("medic", Role.MEDIC),
        ("mechanic", Role.MECHANIC),
        ("client", Role.CLIENT),
        ("dispatcher", Role.DISPATCHER),
        ("predreis", Role.PREDREIS),
    ],
)
def test_role_mapping(raw: str, role: Role) -> None:
    """Роли Предрейса приводятся к ролям журналов."""
    assert parse_role(raw) is role


def test_unknown_role_gets_no_access() -> None:
    """Незнакомая роль не получает доступа, даже если флаг включён."""
    with pytest.raises(ForbiddenError) as exc:
        principal_from_user(user(role="driver"))
    assert exc.value.code == "role_unsupported"


def test_principal_requires_active_account_and_access_flag() -> None:
    """Отключённая учётка — 401, нет флага доступа — 403."""
    with pytest.raises(UnauthorizedError):
        principal_from_user(user(is_active=False))
    with pytest.raises(ForbiddenError) as exc:
        principal_from_user(user(journals_access=False))
    assert exc.value.code == "journals_disabled"


def test_principal_does_not_keep_the_token() -> None:
    """Principal содержит ФИО, роль, организацию и короткий идентификатор сессии, но не токен."""
    org = uuid.uuid4()
    principal = principal_from_user(
        user(role="client", org_id=org), ip="10.0.0.1", token="secret-token"
    )
    assert principal.full_name == "Иванов Иван Иванович" and principal.org_id == org
    assert principal.session_id and "secret-token" not in repr(principal)
    assert len(principal.session_id) == 16


# ---------- HTTP ----------


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Приложение с подставным Предрейсом, часами и ограничителем входа."""
    from app.main import create_app

    fake, clock = FakePredreis(), Clock()
    app = create_app()
    verifier = make_verifier(fake, clock)
    limiter = LoginGuard(per_email=3, per_ip=6, window_s=60, now=clock)
    app.dependency_overrides[get_predreis_client] = lambda: fake
    app.dependency_overrides[get_user_verifier] = lambda: verifier
    app.dependency_overrides[get_login_limiter] = lambda: limiter
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, fake, clock


async def test_api_requires_token(api: Any) -> None:
    """Без токена — 401 в едином формате."""
    client, _, _ = api
    resp = await client.get("/api/v1/me")
    assert resp.status_code == 401 and resp.json()["error"]["code"] == "unauthorized"


async def test_api_accepts_predreis_token(api: Any) -> None:
    """Токен Предрейса принимается; права строятся по роли."""
    client, fake, _ = api
    fake.tokens["sa"] = user(role="superadmin")
    fake.tokens["medic"] = user(id=uuid.uuid4(), role="medic")
    sa = await client.get("/api/v1/me", headers={"Authorization": "Bearer sa"})
    medic = await client.get("/api/v1/me", headers={"Authorization": "Bearer medic"})
    assert sa.status_code == medic.status_code == 200
    assert "medical:ejournal_sign" in sa.json()["permissions"]
    assert "medical:sign" in medic.json()["permissions"]
    assert "medical:ejournal_sign" not in medic.json()["permissions"]


async def test_api_denies_without_journals_access(api: Any) -> None:
    """Нет доступа к журналам — 403 с кодом journals_disabled."""
    client, fake, _ = api
    fake.tokens["nope"] = ForbiddenError(
        "Доступ к журналам не предоставлен", code="journals_disabled"
    )
    resp = await client.get("/api/v1/me", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "journals_disabled"
    bad = await client.get("/api/v1/me", headers={"Authorization": "Bearer unknown"})
    assert bad.status_code == 401


async def test_login_returns_token_profile_and_permissions(api: Any) -> None:
    """Вход теми же почтой и паролем: возвращается токен Предрейса, профиль и права."""
    client, fake, _ = api
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "User@Example.ru", "password": SECRET_PASSWORD}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == "good" and data["expires_in"] == 1800
    assert (
        data["user"]["role"] == "superadmin"
        and data["user"]["full_name"] == "Иванов Иван Иванович"
    )
    assert "medical:ejournal_sign" in data["permissions"]
    assert fake.login_calls == [("user@example.ru", SECRET_PASSWORD)]
    assert SECRET_PASSWORD not in resp.text


async def test_login_wrong_password_and_no_access(api: Any) -> None:
    """Неверный пароль — 401; верный пароль без доступа к журналам — 403."""
    client, fake, _ = api
    fake.password_ok = False
    bad = await client.post("/api/v1/auth/login", json={"email": "u@e.ru", "password": "x"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
    fake.password_ok = True
    fake.tokens["good"] = ForbiddenError(
        "Доступ к журналам не предоставлен", code="journals_disabled"
    )
    denied = await client.post("/api/v1/auth/login", json={"email": "u@e.ru", "password": "x"})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "journals_disabled"


async def test_login_is_rate_limited_by_email(api: Any) -> None:
    """Подбор пароля: после нескольких попыток — 429, Предрейс больше не опрашивается."""
    client, fake, clock = api
    fake.password_ok = False
    codes = [
        (
            await client.post(
                "/api/v1/auth/login", json={"email": "victim@e.ru", "password": f"p{i}"}
            )
        ).status_code
        for i in range(5)
    ]
    assert codes == [401, 401, 401, 429, 429]
    assert len(fake.login_calls) == 3
    clock.now += 61  # окно прошло
    again = await client.post("/api/v1/auth/login", json={"email": "victim@e.ru", "password": "p"})
    assert again.status_code == 401


async def test_password_never_reaches_logs(api: Any, caplog: pytest.LogCaptureFixture) -> None:
    """Пароль не попадает в логи ни при успехе, ни при ошибке."""
    client, fake, _ = api
    with caplog.at_level(logging.DEBUG):
        await client.post(
            "/api/v1/auth/login", json={"email": "a@e.ru", "password": SECRET_PASSWORD}
        )
        fake.password_ok = False
        await client.post(
            "/api/v1/auth/login", json={"email": "a@e.ru", "password": SECRET_PASSWORD}
        )
        await client.post("/api/v1/auth/login", json={"email": "a@e.ru"})  # ошибка валидации
    assert SECRET_PASSWORD not in caplog.text


def test_sliding_window_limiter() -> None:
    """Окно скользит: события старше окна не считаются."""
    clock = Clock()
    limiter = SlidingWindowLimiter(2, 10, clock)
    assert limiter.allow("k") and limiter.allow("k") and not limiter.allow("k")
    clock.now += 11
    assert limiter.allow("k")
    limiter.reset("k")
    assert limiter.allow("k") and limiter.allow("k")


async def test_many_successful_logins_from_one_address_are_not_blocked(api: Any) -> None:
    """Смена диспетчеров за одним адресом (NAT): успешные входы лимит не расходуют."""
    client, _fake, _ = api
    for _ in range(20):
        resp = await client.post("/api/v1/auth/login", json={"email": "u@e.ru", "password": "pw"})
        assert resp.status_code == 200


async def test_failures_per_address_have_a_higher_threshold(api: Any) -> None:
    """Подбор с одного адреса по разным почтам блокируется позже, чем по одной почте."""
    client, fake, _ = api
    fake.password_ok = False
    codes = [
        (
            await client.post(
                "/api/v1/auth/login", json={"email": f"user{i}@e.ru", "password": "bad"}
            )
        ).status_code
        for i in range(9)
    ]
    assert codes == [401] * 6 + [429] * 3  # порог адреса в тесте — 6 неудач
    fake.password_ok = True
    blocked = await client.post(
        "/api/v1/auth/login", json={"email": "fine@e.ru", "password": "ok"}
    )
    assert blocked.status_code == 429  # пока окно не прошло, адрес блокируется целиком


async def test_success_resets_failures_for_that_email(api: Any) -> None:
    """Опечатался и вошёл: счётчик неудач по почте сбрасывается."""
    client, fake, _ = api
    fake.password_ok = False
    for _ in range(2):
        await client.post("/api/v1/auth/login", json={"email": "typo@e.ru", "password": "bad"})
    fake.password_ok = True
    assert (
        await client.post("/api/v1/auth/login", json={"email": "typo@e.ru", "password": "ok"})
    ).status_code == 200
    fake.password_ok = False
    after = [
        (
            await client.post("/api/v1/auth/login", json={"email": "typo@e.ru", "password": "bad"})
        ).status_code
        for _ in range(3)
    ]
    assert after == [401, 401, 401]  # снова три неудачи подряд до блокировки


def test_login_guard_counts_only_failures() -> None:
    """Проверка и учёт раздельны: is_blocked сама попыток не считает."""
    clock = Clock()
    guard = LoginGuard(per_email=2, per_ip=10, window_s=10, now=clock)
    for _ in range(5):
        assert not guard.is_blocked("1.1.1.1", "a@e.ru")
    guard.failure("1.1.1.1", "a@e.ru")
    guard.failure("1.1.1.1", "a@e.ru")
    assert guard.is_blocked("1.1.1.1", "a@e.ru") and not guard.is_blocked("1.1.1.1", "b@e.ru")
    clock.now += 11
    assert not guard.is_blocked("1.1.1.1", "a@e.ru")

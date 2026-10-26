"""Весь путь через HTTP: роутеры, права, формат ошибок, PDF и ZIP (проверяется то, что увидит фронтенд)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.errors import UnauthorizedError
from app.core.ratelimit import LoginGuard
from app.core.security import UserVerifier, get_user_verifier
from app.core.storage import LocalStorage, get_storage
from app.integrations.predreis.client import VerifiedUser, get_predreis_client, get_sign_gateway
from app.modules.auth.router import get_login_limiter
from app.modules.ejournal.container import verify_container
from app.modules.ejournal.service import EJournalService
from app.modules.signing.service import SigningService
from tests.factories import FakeSigner, World, seed
from tests.test_security import Clock, FakePredreis

pytestmark = pytest.mark.asyncio
MSK = timezone(timedelta(hours=3))
WHEN = datetime(2026, 10, 14, 8, 20, tzinfo=MSK)


@dataclass
class Stack:
    """Приложение с подставными внешними системами и данными тестового мира."""

    client: httpx.AsyncClient
    world: World
    gateway: FakeSigner
    predreis: FakePredreis
    storage: LocalStorage
    sessions: async_sessionmaker[AsyncSession]

    def auth(self, who: str) -> dict[str, str]:
        """Заголовок авторизации для роли из тестового набора."""
        return {"Authorization": f"Bearer {who}"}

    async def run_worker(self) -> None:
        """Один проход воркера подписи (как задача ARQ)."""
        async with self.sessions() as session:
            journals = EJournalService(session, self.gateway, storage=self.storage)
            await SigningService(
                session, self.gateway, self.storage, journal_finisher=journals
            ).process_jobs()


def _user(uid: uuid.UUID, role: str, org: uuid.UUID | None = None) -> VerifiedUser:
    """Пользователь Предрейса с доступом к журналам."""
    return VerifiedUser(uid, f"{role}@e.ru", role.title(), "Тестов", None, role, org, True, True)


@pytest_asyncio.fixture
async def stack(
    session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Stack]:
    """Поднимает приложение: БД и файлы — настоящие, Предрейс и шлюз подписи — подставные."""
    from app.main import create_app

    monkeypatch.setenv("JOURNALS_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    get_storage.cache_clear()
    world = await seed(session)
    predreis, clock, gateway = FakePredreis(), Clock(), FakeSigner()
    predreis.tokens = {
        "medic": _user(world.medic.id, "medic"),
        "mechanic": _user(world.mechanic.id, "mechanic"),
        "manager": _user(world.manager.id, "predreis"),
        "sa": _user(uuid.uuid4(), "superadmin"),
        "client": _user(uuid.uuid4(), "client", world.org.id),
    }
    sessions = async_sessionmaker(session.bind, expire_on_commit=False)  # type: ignore[arg-type]

    async def db() -> AsyncIterator[AsyncSession]:
        """Сессия на запрос, как в проде."""
        async with sessions() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = db
    app.dependency_overrides[get_user_verifier] = lambda: UserVerifier(predreis, Settings(), clock)  # type: ignore[arg-type]
    app.dependency_overrides[get_sign_gateway] = lambda: gateway
    app.dependency_overrides[get_predreis_client] = lambda: predreis
    app.dependency_overrides[get_login_limiter] = lambda: LoginGuard(100, 100, 60, clock)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield Stack(client, world, gateway, predreis, LocalStorage(tmp_path), sessions)
    get_settings.cache_clear()
    get_storage.cache_clear()


def medical_body(w: World, **over: Any) -> dict[str, Any]:
    """Тело запроса на создание записи медосмотра."""
    return {
        "organization_id": str(w.org.id),
        "driver_id": str(w.driver.id),
        "phase": "pre",
        "performed_at": WHEN.isoformat(),
        "bp_systolic": 137,
        "bp_diastolic": 84,
        "pulse": 72,
        "temperature": "36.6",
        "result": "admitted",
    } | over


async def test_full_scenario_over_http(stack: Stack) -> None:
    """Вход → запись → подпись → PDF → электронный журнал → ZIP; права по ролям на каждом шаге."""
    c, w = stack.client, stack.world
    # --- запись медика ---
    created = await c.post(
        "/api/v1/medical/records", json=medical_body(w), headers=stack.auth("medic")
    )
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["status"] == "unsigned" and {"sign", "edit", "delete"} <= set(record["actions"])
    assert record["signing_status"] is None and record["snapshot"]["driver"]["full_name"]

    # --- постановка на подпись; пока идёт подпись, запись закрыта ---
    sign = await c.post(
        "/api/v1/medical/records/sign",
        json={"record_ids": [record["id"]]},
        headers=stack.auth("medic"),
    )
    assert sign.status_code == 200 and sign.json()["signed"] == 1
    busy = await c.get(f"/api/v1/medical/records/{record['id']}", headers=stack.auth("medic"))
    assert busy.json()["signing_status"] in {"queued", "pending"} and busy.json()["actions"] == []
    blocked = await c.patch(
        f"/api/v1/medical/records/{record['id']}", json={"pulse": 70}, headers=stack.auth("medic")
    )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "signing_in_progress"

    await stack.run_worker()
    done = await c.get(f"/api/v1/medical/records/{record['id']}", headers=stack.auth("medic"))
    assert done.json()["status"] == "signed" and done.json()["signature"]["cert_serial"]
    assert done.json()["actions"] == []  # подписанную запись медик менять не может

    # --- выгрузка PDF менеджером ---
    export = await c.post(
        "/api/v1/exports/medical",
        json={
            "organization_id": str(w.org.id),
            "date_from": "2026-10-14",
            "date_to": "2026-10-14",
        },
        headers=stack.auth("manager"),
    )
    assert export.status_code == 200 and export.headers["content-type"] == "application/pdf"
    assert export.content.startswith(b"%PDF")
    disposition = export.headers["content-disposition"]
    assert (
        unquote(disposition.split("UTF-8''")[1])
        == "Отчёт о медосмотрах ПРЕДРЕЙС_с 14.10.2026 по 14.10.2026.pdf"
    )

    # --- клиент ЭПЛ-организации: только подписанное и без медицинских показателей ---
    seen = await c.get("/api/v1/medical/records", headers=stack.auth("client"))
    assert seen.status_code == 200 and seen.json()["total"] == 1
    raw = seen.text
    for secret in (
        "complaints",
        "bp_systolic",
        "pulse",
        "temperature",
        "alcohol_mgl",
        "harmful_factors",
    ):
        assert secret not in raw
    denied = await c.post(
        "/api/v1/medical/records", json=medical_body(w), headers=stack.auth("client")
    )
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "permission_denied"

    # --- электронный журнал ---
    payload = {
        "kind": "medical",
        "organization_id": str(w.org.id),
        "period_from": "2026-10-14",
        "period_to": "2026-10-14",
    }
    assert (
        await c.post("/api/v1/ejournals", json=payload, headers=stack.auth("medic"))
    ).status_code == 403
    draft = (await c.post("/api/v1/ejournals", json=payload, headers=stack.auth("manager"))).json()
    assert draft["status"] == "draft" and draft["record_count"] == 1
    submitted = await c.post(
        f"/api/v1/ejournals/{draft['id']}/submit", headers=stack.auth("manager")
    )
    assert submitted.json()["status"] == "awaiting_signature"
    preview = await c.get(f"/api/v1/ejournals/{draft['id']}/preview", headers=stack.auth("sa"))
    assert preview.status_code == 200 and preview.content.startswith(b"%PDF")
    early = await c.get(f"/api/v1/ejournals/{draft['id']}/download", headers=stack.auth("manager"))
    assert early.status_code == 404  # ZIP появляется только после подписи

    assert (
        await c.post(f"/api/v1/ejournals/{draft['id']}/sign", headers=stack.auth("manager"))
    ).status_code == 403
    signing = await c.post(f"/api/v1/ejournals/{draft['id']}/sign", headers=stack.auth("sa"))
    assert signing.json()["status"] == "signing"
    await stack.run_worker()
    final = await c.get(f"/api/v1/ejournals/{draft['id']}", headers=stack.auth("sa"))
    assert final.json()["status"] == "signed"
    zipped = await c.get(
        f"/api/v1/ejournals/{draft['id']}/download", headers=stack.auth("manager")
    )
    assert zipped.status_code == 200 and zipped.headers["content-type"] == "application/zip"
    assert verify_container(zipped.content) == []
    assert (
        await c.get(f"/api/v1/ejournals/{draft['id']}/download", headers=stack.auth("client"))
    ).status_code == 403
    after = await c.get(f"/api/v1/medical/records/{record['id']}", headers=stack.auth("manager"))
    assert after.json()["status"] == "in_journal" and after.json()["actions"] == []


async def test_validation_and_error_format(stack: Stack) -> None:
    """Единый формат ошибок: 401, 404, 422 с перечнем проблем."""
    c, w = stack.client, stack.world
    no_auth = await c.get("/api/v1/medical/records")
    assert no_auth.status_code == 401 and set(no_auth.json()["error"]) == {
        "code",
        "message",
        "details",
    }
    missing = await c.get(f"/api/v1/medical/records/{uuid.uuid4()}", headers=stack.auth("manager"))
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"

    bad = medical_body(w, temperature="50.0", pulse=5, performed_at="2026-10-14T08:20:00")
    resp = await c.post("/api/v1/medical/records", json=bad, headers=stack.auth("medic"))
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "request_invalid"
    fields = {tuple(e["loc"])[-1] for e in resp.json()["error"]["details"]}
    assert {"temperature", "pulse", "performed_at"} <= fields
    wrong_org = await c.post(
        "/api/v1/medical/records",
        json=medical_body(w, driver_id=str(uuid.uuid4())),
        headers=stack.auth("medic"),
    )
    assert wrong_org.status_code == 422 and wrong_org.json()["error"]["code"] == "driver_invalid"


async def test_pagination_filters_and_ordering(stack: Stack) -> None:
    """Страницы, сортировка «новые первыми», фильтры и границы page_size."""
    c, w = stack.client, stack.world
    for day in range(12):
        body = medical_body(w, performed_at=(WHEN + timedelta(days=day)).isoformat())
        assert (
            await c.post("/api/v1/medical/records", json=body, headers=stack.auth("medic"))
        ).status_code == 201
    h = stack.auth("manager")
    page = (await c.get("/api/v1/medical/records?page=2&page_size=5", headers=h)).json()
    assert (page["total"], page["page"], page["page_size"], len(page["items"])) == (12, 2, 5, 5)
    dates = [
        i["performed_at"]
        for i in (await c.get("/api/v1/medical/records?page_size=12", headers=h)).json()["items"]
    ]
    assert dates == sorted(dates, reverse=True)
    default = (await c.get("/api/v1/medical/records", headers=h)).json()
    assert default["page_size"] == 10 and len(default["items"]) == 10
    in_range = (
        await c.get("/api/v1/medical/records?date_from=2026-10-20&date_to=2026-10-22", headers=h)
    ).json()
    assert in_range["total"] == 3
    assert (await c.get("/api/v1/medical/records?driver_name=ефимов", headers=h)).json()[
        "total"
    ] == 12
    assert (await c.get("/api/v1/medical/records?driver_name=несуществующий", headers=h)).json()[
        "total"
    ] == 0
    assert (await c.get(f"/api/v1/medical/records?driver_id={w.driver.id}", headers=h)).json()[
        "total"
    ] == 12
    assert (await c.get(f"/api/v1/medical/records?driver_id={uuid.uuid4()}", headers=h)).json()[
        "total"
    ] == 0
    short = await c.get("/api/v1/medical/records?driver_name=еф", headers=h)  # поиск от 3 символов
    assert short.status_code == 422
    assert (await c.get("/api/v1/medical/records?is_signed=true", headers=h)).json()["total"] == 0
    assert (await c.get("/api/v1/medical/records?page_size=1000", headers=h)).status_code == 422
    assert (await c.get("/api/v1/medical/records?page=0", headers=h)).status_code == 422


@pytest.mark.parametrize(
    ("who", "method", "path", "status"),
    [
        ("medic", "GET", "/api/v1/medical/records", 200),
        ("medic", "GET", "/api/v1/technical/records", 403),
        ("mechanic", "GET", "/api/v1/technical/records", 200),
        ("mechanic", "GET", "/api/v1/medical/records", 403),
        ("client", "GET", "/api/v1/medical/records", 200),
        ("client", "GET", "/api/v1/catalog/organizations", 403),
        ("manager", "GET", "/api/v1/catalog/organizations", 200),
        ("medic", "GET", "/api/v1/catalog/drivers", 403),
        ("medic", "GET", "/api/v1/deletion-requests", 403),
        ("sa", "GET", "/api/v1/deletion-requests", 200),
        ("medic", "GET", "/api/v1/ejournals", 403),
        ("manager", "GET", "/api/v1/ejournals", 200),
        ("medic", "GET", "/api/v1/stats/overview", 200),
        ("client", "GET", "/api/v1/stats/overview", 403),
        ("manager", "POST", "/api/v1/ocr/batches", 422),
        ("medic", "POST", "/api/v1/ocr/batches", 403),
    ],
)
async def test_permission_matrix_over_http(
    stack: Stack, who: str, method: str, path: str, status: int
) -> None:
    """Права по ролям на уровне HTTP совпадают с ТЗ."""
    resp = await stack.client.request(method, path, headers=stack.auth(who))
    assert resp.status_code == status, resp.text


async def test_login_over_http_sets_up_a_working_session(stack: Stack) -> None:
    """Вход возвращает токен; с ним доступны методы, а права в ответе совпадают с /me."""
    stack.predreis.tokens["good"] = _user(stack.world.manager.id, "predreis")
    login = await stack.client.post(
        "/api/v1/auth/login", json={"email": "m@e.ru", "password": "pw"}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    me = await stack.client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["permissions"] == login.json()["permissions"]


async def test_health_endpoints(stack: Stack) -> None:
    """Liveness и readiness (с проверкой БД)."""
    assert (await stack.client.get("/health")).json() == {"status": "ok"}
    assert (await stack.client.get("/ready")).json() == {"status": "ready"}


async def test_unauthorized_error_for_bad_token(stack: Stack) -> None:
    """Неизвестный токен — 401."""
    resp = await stack.client.get("/api/v1/me", headers=stack.auth("unknown"))
    assert resp.status_code == 401
    assert isinstance(UnauthorizedError("x"), Exception)

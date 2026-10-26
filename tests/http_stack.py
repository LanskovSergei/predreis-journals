"""Общий стенд HTTP-тестов: приложение с подставными внешними системами и данными тестового мира."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.ratelimit import LoginGuard
from app.core.security import UserVerifier, get_user_verifier
from app.core.storage import LocalStorage, get_storage
from app.integrations.predreis.client import VerifiedUser, get_predreis_client, get_sign_gateway
from app.modules.auth.router import get_login_limiter
from app.modules.ejournal.service import EJournalService
from app.modules.signing.service import SigningService
from tests.factories import FakeSigner, World, seed
from tests.test_security import Clock, FakePredreis

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


def verified_user(uid: uuid.UUID, role: str, org: uuid.UUID | None = None) -> VerifiedUser:
    """Пользователь Предрейса с доступом к журналам."""
    return VerifiedUser(uid, f"{role}@e.ru", role.title(), "Тестов", None, role, org, True, True)


async def build_stack(
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
        "medic": verified_user(world.medic.id, "medic"),
        "mechanic": verified_user(world.mechanic.id, "mechanic"),
        "manager": verified_user(world.manager.id, "predreis"),
        "sa": verified_user(uuid.uuid4(), "superadmin"),
        "client": verified_user(uuid.uuid4(), "client", world.org.id),
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

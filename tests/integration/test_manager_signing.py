"""Запуск подписи ручной записи менеджером за специалиста (настройка JOURNALS_MANAGERS_CAN_SIGN_RECORDS)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.audit import AuditLog
from tests.http_stack import Stack, medical_body, verified_user

pytestmark = pytest.mark.asyncio


@pytest.fixture
def managers_sign(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Включает запуск подписи менеджерами на время теста."""
    monkeypatch.setenv("JOURNALS_MANAGERS_CAN_SIGN_RECORDS", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_by_default_only_the_specialist_signs(stack: Stack) -> None:
    """По умолчанию как в ТЗ: менеджер подпись не запускает, кнопки «Подписать» у него нет."""
    c, w = stack.client, stack.world
    rid = (
        await c.post("/api/v1/medical/records", json=medical_body(w), headers=stack.auth("medic"))
    ).json()["id"]
    assert (
        "sign"
        not in (
            await c.get(f"/api/v1/medical/records/{rid}", headers=stack.auth("manager"))
        ).json()["actions"]
    )
    denied = await c.post(
        "/api/v1/medical/records/sign", json={"record_ids": [rid]}, headers=stack.auth("manager")
    )
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "permission_denied"


async def test_manager_signs_on_behalf_of_the_record_specialist(
    stack: Stack, managers_sign: None
) -> None:
    """Включено: менеджер запускает подпись, подписантом уходит медик из записи, в аудите — кто запустил."""
    c, w = stack.client, stack.world
    rid = (
        await c.post("/api/v1/medical/records", json=medical_body(w), headers=stack.auth("medic"))
    ).json()["id"]
    assert (
        "sign"
        in (await c.get(f"/api/v1/medical/records/{rid}", headers=stack.auth("manager"))).json()[
            "actions"
        ]
    )

    result = await c.post(
        "/api/v1/medical/records/sign", json={"record_ids": [rid]}, headers=stack.auth("manager")
    )
    assert result.status_code == 200 and result.json()["signed"] == 1, result.text
    call = stack.gateway.calls[-1]
    assert call.signer_user_id == w.medic.id  # подписант — специалист, проводивший осмотр
    assert call.requested_by_user_id == w.manager.id  # запустил менеджер (для аудита Предрейса)
    await stack.run_worker()
    signed = (await c.get(f"/api/v1/medical/records/{rid}", headers=stack.auth("manager"))).json()
    assert signed["status"] == "signed" and signed["signature"]["cert_serial"]

    async with stack.sessions() as session:
        audit = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "record.sign_requested")
            )
        ).scalar_one()
    assert audit.payload["on_behalf_of"] == str(w.medic.id) and audit.actor_id == str(w.manager.id)


async def test_setting_does_not_widen_rights_of_other_roles(
    stack: Stack, managers_sign: None
) -> None:
    """Настройка касается только менеджерских ролей: чужой медик и клиент по-прежнему не подписывают."""
    c, w = stack.client, stack.world
    rid = (
        await c.post("/api/v1/medical/records", json=medical_body(w), headers=stack.auth("medic"))
    ).json()["id"]
    stack.predreis.tokens["medic_b"] = verified_user(uuid.uuid4(), "medic")
    other = await c.post(
        "/api/v1/medical/records/sign", json={"record_ids": [rid]}, headers=stack.auth("medic_b")
    )
    assert other.json()["results"][0]["code"] == "not_record_specialist"
    client = await c.post(
        "/api/v1/medical/records/sign", json={"record_ids": [rid]}, headers=stack.auth("client")
    )
    assert client.status_code == 403
    # правила подписи для менеджера те же: запись с примечанием подписать нельзя
    noted = (
        await c.post(
            "/api/v1/medical/records",
            json=medical_body(w, note="проверить"),
            headers=stack.auth("medic"),
        )
    ).json()["id"]
    refused = await c.post(
        "/api/v1/medical/records/sign", json={"record_ids": [noted]}, headers=stack.auth("manager")
    )
    assert refused.json()["results"][0]["code"] == "note_not_empty"

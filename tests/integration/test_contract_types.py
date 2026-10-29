"""Вид договора (решение заказчика): «мед» — только медосмотры, «тех» — только техконтроль, «медтех» — оба."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.catalog import Organization
from app.models.integration import InboxFailure
from app.workers.consumer import Outcome, process_body
from tests.factories import seed
from tests.http_stack import WHEN, Stack, medical_body
from tests.integration.test_consumer_and_sync import body, exam_payload, factory
from tests.integration.test_frontend_contract import _signed

pytestmark = pytest.mark.asyncio


def tech_body(stack: Stack, **over: Any) -> dict[str, Any]:
    """Тело записи техконтроля."""
    w = stack.world
    return {"organization_id": str(w.org.id), "vehicle_id": str(w.vehicle.id), "performed_at": WHEN.isoformat(),
            "odometer": 1000, "result": "admitted"} | over  # fmt: skip


async def _set_contract(stack: Stack, contract: str | None) -> None:
    """Вид договора организации тестового мира (поле журналов, у организаций из платформы правится)."""
    resp = await stack.client.patch(
        f"/api/v1/catalog/organizations/{stack.world.org.id}",
        json={"contract_type": contract},
        headers=stack.auth("manager"),
    )
    assert resp.status_code == 200, resp.text


async def test_med_contract_has_no_technical_journal(stack: Stack) -> None:
    """Договор «мед»: техконтроль не создаётся, медосмотр — как обычно."""
    c = stack.client
    await _set_contract(stack, "med")
    tech = await c.post(
        "/api/v1/technical/records", json=tech_body(stack), headers=stack.auth("mechanic")
    )
    assert tech.status_code == 422 and tech.json()["error"]["code"] == "contract_excludes_journal"
    med = await c.post(
        "/api/v1/medical/records", json=medical_body(stack.world), headers=stack.auth("medic")
    )
    assert med.status_code == 201


async def test_tech_contract_has_no_medical_journal(stack: Stack) -> None:
    """Договор «тех»: медосмотр не создаётся, в том числе электронный журнал медосмотров."""
    c = stack.client
    await _set_contract(stack, "tech")
    med = await c.post(
        "/api/v1/medical/records", json=medical_body(stack.world), headers=stack.auth("medic")
    )
    assert med.status_code == 422 and med.json()["error"]["code"] == "contract_excludes_journal"
    journal = await c.post(
        "/api/v1/ejournals",
        json={"kind": "medical", "organization_id": str(stack.world.org.id), "period_from": "2026-10-01", "period_to": "2026-10-31"},
        headers=stack.auth("manager"),
    )  # fmt: skip
    assert (
        journal.status_code == 422
        and journal.json()["error"]["code"] == "contract_excludes_journal"
    )


async def test_client_sees_only_journals_of_the_contract(stack: Stack) -> None:
    """Клиент организации с договором «мед» видит только медосмотры; раздел техконтроля ему не показывается."""
    c = stack.client
    await _signed(stack)
    await _set_contract(stack, "med")
    client = stack.auth("client")
    assert (await c.get("/api/v1/me", headers=client)).json()["journals"] == ["medical"]
    assert (await c.get("/api/v1/medical/records", headers=client)).json()["total"] == 1
    hidden = await c.get("/api/v1/technical/records", headers=client)
    assert (
        hidden.status_code == 403 and hidden.json()["error"]["code"] == "contract_excludes_journal"
    )
    export = await c.post("/api/v1/exports/technical", json={}, headers=client)
    assert export.status_code == 403
    await _set_contract(stack, "medtech")
    assert (await c.get("/api/v1/me", headers=client)).json()["journals"] == [
        "medical",
        "technical",
    ]


async def test_journals_in_profile_follow_the_role(stack: Stack) -> None:
    """Список журналов в /me: медик — медосмотры, механик — техконтроль, менеджер — оба."""
    c = stack.client
    assert (await c.get("/api/v1/me", headers=stack.auth("medic"))).json()["journals"] == [
        "medical"
    ]
    assert (await c.get("/api/v1/me", headers=stack.auth("mechanic"))).json()["journals"] == [
        "technical"
    ]
    assert (await c.get("/api/v1/me", headers=stack.auth("manager"))).json()["journals"] == [
        "medical",
        "technical",
    ]
    assert (await c.get("/api/v1/me", headers=stack.auth("client"))).json()["journals"] == [
        "medical",
        "technical",
    ]


async def test_epl_event_outside_the_contract_goes_to_failures(
    session: AsyncSession, storage: Any
) -> None:
    """Событие техконтроля ЭПЛ для организации с договором «мед» не создаёт запись и видно оператору."""
    w = await seed(session)
    await session.execute(
        update(Organization).where(Organization.id == w.org.id).values(contract_type="med")
    )
    await session.commit()
    outcome = await process_body(
        body(
            exam_payload(w, "event_technical.json", exam_datetime="2026-10-14T08:20:00+03:00"),
            "journal.technical_exam",
        ),
        factory(session),
        storage,
        Settings(),
    )
    assert outcome is Outcome.ACK  # недопустимое событие подтверждается и уходит в таблицу ошибок
    from app.models.records import TechnicalRecord

    assert (
        await session.execute(select(TechnicalRecord))
    ).scalars().all() == []  # запись не создана
    failure = (await session.execute(select(InboxFailure))).scalar_one()
    assert "contract_excludes_journal" in (failure.reason + (failure.detail or ""))

"""Правила по датам (пояснения заказчика): записи задним числом, поздняя подпись, журнал по периоду."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.http_stack import Stack, medical_body
from tests.integration.test_frontend_contract import _signed

pytestmark = pytest.mark.asyncio
MAY = datetime(2026, 5, 14, 5, 20, tzinfo=timezone.utc)  # 14 мая, 08:20 по Москве
MAY_PERIOD = {"period_from": "2026-05-01", "period_to": "2026-05-31"}


async def test_record_for_may_can_be_created_now_and_signed_later(stack: Stack) -> None:
    """В октябре можно внести запись за май, а подписать её когда угодно: ограничений по датам нет."""
    c, w = stack.client, stack.world
    created = await c.post(
        "/api/v1/medical/records",
        json=medical_body(w, performed_at=MAY.isoformat()),
        headers=stack.auth("medic"),
    )
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    sign = await c.post(
        "/api/v1/medical/records/sign", json={"record_ids": [rid]}, headers=stack.auth("medic")
    )
    assert sign.json()["signed"] == 1
    await stack.run_worker()
    assert (await c.get(f"/api/v1/medical/records/{rid}", headers=stack.auth("medic"))).json()[
        "status"
    ] == "signed"


async def test_late_records_go_into_the_next_journal_for_the_same_period(stack: Stack) -> None:
    """Отправленный журнал за май «прибит гвоздём»; запись за май, внесённая позже, — в следующем журнале за май."""
    c, w = stack.client, stack.world
    await _signed(stack, performed_at=MAY.isoformat())
    manager = stack.auth("manager")
    body = {"kind": "medical", "organization_id": str(w.org.id)} | MAY_PERIOD
    first = (await c.post("/api/v1/ejournals", json=body, headers=manager)).json()
    submitted = await c.post(f"/api/v1/ejournals/{first['id']}/submit", headers=manager)
    assert submitted.status_code == 200 and submitted.json()["record_count"] == 1

    await _signed(
        stack, performed_at=(MAY + timedelta(days=3)).isoformat()
    )  # внесли задним числом
    second = await c.post("/api/v1/ejournals", json=body, headers=manager)
    assert second.status_code == 201 and second.json()["record_count"] == 1  # только новая запись
    assert second.json()["id"] != first["id"]


async def test_one_record_never_gets_into_two_journals(stack: Stack) -> None:
    """Два черновика за один период: запись закрепляется за тем, что отправлен первым; второй — без неё."""
    c, w = stack.client, stack.world
    await _signed(stack, performed_at=MAY.isoformat())
    manager = stack.auth("manager")
    body = {"kind": "medical", "organization_id": str(w.org.id)} | MAY_PERIOD
    a = (await c.post("/api/v1/ejournals", json=body, headers=manager)).json()
    b = (await c.post("/api/v1/ejournals", json=body, headers=manager)).json()
    assert a["record_count"] == b["record_count"] == 1  # в черновике число предварительное
    assert (
        await c.post(f"/api/v1/ejournals/{a['id']}/submit", headers=manager)
    ).status_code == 200
    late = await c.post(f"/api/v1/ejournals/{b['id']}/submit", headers=manager)
    assert late.status_code == 422  # запись уже закреплена за первым журналом


async def test_journal_without_new_signed_records_is_not_created(stack: Stack) -> None:
    """Если за период нет подписанных записей вне других журналов, пустой журнал не создаётся."""
    w = stack.world
    resp = await stack.client.post(
        "/api/v1/ejournals",
        json={"kind": "medical", "organization_id": str(w.org.id)} | MAY_PERIOD,
        headers=stack.auth("manager"),
    )
    assert resp.status_code == 422

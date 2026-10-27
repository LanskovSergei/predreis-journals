"""Контракт для фронтенда: каждое утверждение руководства docs/FRONTEND.md проверено через HTTP."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

from tests.http_stack import WHEN, Stack, medical_body
from tests.integration.test_ejournal_container import _ingest

pytestmark = pytest.mark.asyncio


async def _signed(stack: Stack, kind: str = "medical", who: str = "medic", **over: Any) -> str:
    """Создаёт запись, ставит на подпись, прогоняет воркер; возвращает идентификатор подписанной."""
    w = stack.world
    if kind == "medical":
        body = medical_body(w, **over)
    else:
        body = {
            "organization_id": str(w.org.id),
            "vehicle_id": str(w.vehicle.id),
            "performed_at": WHEN.isoformat(),
            "odometer": 1000,
            "result": "admitted",
        } | over
    created = await stack.client.post(
        f"/api/v1/{kind}/records", json=body, headers=stack.auth(who)
    )
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    signing = await stack.client.post(
        f"/api/v1/{kind}/records/sign", json={"record_ids": [rid]}, headers=stack.auth(who)
    )
    assert signing.json()["signed"] == 1, signing.text
    await stack.run_worker()
    state = await stack.client.get(f"/api/v1/{kind}/records/{rid}", headers=stack.auth(who))
    assert state.json()["status"] == "signed", state.text
    return str(rid)


async def test_note_blocks_signing_until_cleared(stack: Stack) -> None:
    """Запись с примечанием: строка выделяется, подписать нельзя, «Снять примечание» возвращает подпись."""
    c = stack.client
    created = await c.post(
        "/api/v1/medical/records",
        json=medical_body(stack.world, note="проверить АД"),
        headers=stack.auth("medic"),
    )
    rec = created.json()
    assert rec["has_note"] is True and rec["note"] == "проверить АД"
    assert "clear_note" in rec["actions"]

    sign = await c.post(
        "/api/v1/medical/records/sign",
        json={"record_ids": [rec["id"]]},
        headers=stack.auth("medic"),
    )
    assert sign.json()["failed"] == 1 and sign.json()["results"][0]["code"] == "note_not_empty"

    cleared = await c.post(
        f"/api/v1/medical/records/{rec['id']}/clear-note", headers=stack.auth("medic")
    )
    assert (
        cleared.status_code == 200
        and cleared.json()["has_note"] is False
        and cleared.json()["note"] is None
    )
    assert "sign" in cleared.json()["actions"] and "clear_note" not in cleared.json()["actions"]
    assert (
        await c.post(
            "/api/v1/medical/records/sign",
            json={"record_ids": [rec["id"]]},
            headers=stack.auth("medic"),
        )
    ).json()["signed"] == 1


async def test_deletion_request_approved_by_admin(stack: Stack) -> None:
    """Подписанную запись удаляют через запрос: создаёт менеджер ПРЕДРЕЙС, решает Админ или СА."""
    c = stack.client
    rid = await _signed(stack)
    assert (
        await c.post(
            f"/api/v1/medical/records/{rid}/deletion-request", json={}, headers=stack.auth("medic")
        )
    ).status_code == 403

    created = await c.post(
        f"/api/v1/medical/records/{rid}/deletion-request",
        json={"reason": "ошибочная запись"},
        headers=stack.auth("manager"),
    )
    assert created.status_code == 201 and created.json()["status"] == "pending"
    req_id = created.json()["id"]
    pending = (await c.get(f"/api/v1/medical/records/{rid}", headers=stack.auth("manager"))).json()
    assert pending["deletion_pending"] is True and "request_deletion" not in pending["actions"]

    assert (
        await c.get("/api/v1/deletion-requests", headers=stack.auth("manager"))
    ).status_code == 403
    listed = await c.get("/api/v1/deletion-requests", headers=stack.auth("admin"))
    assert listed.status_code == 200 and [r["record_id"] for r in listed.json()] == [rid]
    assert (
        await c.post(
            f"/api/v1/deletion-requests/{req_id}/approve", json={}, headers=stack.auth("manager")
        )
    ).status_code == 403

    approved = await c.post(
        f"/api/v1/deletion-requests/{req_id}/approve",
        json={"comment": "согласовано"},
        headers=stack.auth("admin"),
    )
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert approved.json()["resolution_comment"] == "согласовано"
    assert (
        await c.get(f"/api/v1/medical/records/{rid}", headers=stack.auth("manager"))
    ).status_code == 404
    assert (
        await c.get("/api/v1/deletion-requests", headers=stack.auth("sa"))
    ).json() == []  # ожидающих больше нет
    done = await c.get(
        "/api/v1/deletion-requests?status_filter=approved", headers=stack.auth("sa")
    )
    assert [r["id"] for r in done.json()] == [req_id]
    again = await c.post(
        f"/api/v1/deletion-requests/{req_id}/approve", json={}, headers=stack.auth("admin")
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_resolved"


async def test_deletion_request_rejected_keeps_the_record(stack: Stack) -> None:
    """Отклонённый запрос оставляет запись на месте и снимает пометку «на удалении»."""
    c = stack.client
    rid = await _signed(stack)
    req = (
        await c.post(
            f"/api/v1/medical/records/{rid}/deletion-request",
            json={},
            headers=stack.auth("manager"),
        )
    ).json()
    rejected = await c.post(
        f"/api/v1/deletion-requests/{req['id']}/reject",
        json={"comment": "запись верна"},
        headers=stack.auth("sa"),
    )
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    record = (await c.get(f"/api/v1/medical/records/{rid}", headers=stack.auth("manager"))).json()
    assert record["status"] == "signed" and record["deletion_pending"] is False


async def test_direct_deletion_of_signed_record(stack: Stack) -> None:
    """Админ и СА удаляют подписанную запись сразу; остальным нельзя; из ЭПЛ не удаляется никем."""
    c = stack.client
    rid = await _signed(stack)
    for role in ("medic", "manager"):
        assert (
            await c.delete(f"/api/v1/records/medical/{rid}/signed", headers=stack.auth(role))
        ).status_code == 403
    assert (
        await c.delete(f"/api/v1/records/medical/{rid}/signed", headers=stack.auth("sa"))
    ).status_code == 204
    assert (
        await c.get(f"/api/v1/medical/records/{rid}", headers=stack.auth("sa"))
    ).status_code == 404

    async with stack.sessions() as session:
        await _ingest(session, stack.storage, "T2", stack.world)
    epl = (await c.get("/api/v1/medical/records?page_size=5", headers=stack.auth("sa"))).json()[
        "items"
    ]
    assert epl and epl[0]["source"] == "epl" and epl[0]["actions"] == []
    blocked = await c.delete(
        f"/api/v1/records/medical/{epl[0]['id']}/signed", headers=stack.auth("sa")
    )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "epl_immutable"


async def test_catalog_search_and_filters(stack: Stack) -> None:
    """Справочники: поиск `q`, фильтр по организации, доступ только менеджерским ролям."""
    c, w = stack.client, stack.world
    h = stack.auth("manager")
    orgs = await c.get("/api/v1/catalog/organizations?q=Тест", headers=h)
    assert orgs.status_code == 200 and orgs.json()["total"] >= 1
    assert (
        await c.get("/api/v1/catalog/organizations?q=нет-такой-организации", headers=h)
    ).json()["total"] == 0
    drivers = await c.get(
        f"/api/v1/catalog/drivers?organization_id={w.org.id}&q=Ефимов", headers=h
    )
    assert drivers.json()["total"] == 1 and drivers.json()["items"][0]["full_name"].startswith(
        "Ефимов"
    )
    vehicles = await c.get(f"/api/v1/catalog/vehicles?organization_id={w.org.id}", headers=h)
    assert vehicles.status_code == 200 and vehicles.json()["items"][0]["plate"] == "О224ЕК790"
    assert (await c.get("/api/v1/catalog/vehicles?q=О224", headers=h)).json()["total"] == 1
    assert (
        await c.get("/api/v1/catalog/vehicles", headers=stack.auth("client"))
    ).status_code == 403
    assert (
        await c.get("/api/v1/catalog/vehicles", headers=stack.auth("mechanic"))
    ).status_code == 403


async def test_technical_flow_over_http(stack: Stack) -> None:
    """Техконтроль: создание, асинхронная подпись, выгрузка PDF, просмотр клиентом, фильтр по ТС."""
    c, w = stack.client, stack.world
    rid = await _signed(stack, "technical", "mechanic")
    record = (
        await c.get(f"/api/v1/technical/records/{rid}", headers=stack.auth("mechanic"))
    ).json()
    assert record["signature"]["cert_serial"] and record["actions"] == []

    export = await c.post(
        "/api/v1/exports/technical",
        json={
            "organization_id": str(w.org.id),
            "date_from": "2026-10-14",
            "date_to": "2026-10-14",
        },
        headers=stack.auth("manager"),
    )
    assert export.status_code == 200 and export.content.startswith(b"%PDF")
    assert (
        "%D0%9E%D1%82%D1%87%D1%91%D1%82%20%D0%BE%20%D1%82%D0%B5%D1%85%D0%BA%D0%BE%D0%BD%D1%82%D1%80%D0%BE%D0%BB%D0%B5"
        in export.headers["content-disposition"]
    )

    assert (
        await c.get(
            f"/api/v1/technical/records?vehicle_id={w.vehicle.id}", headers=stack.auth("manager")
        )
    ).json()["total"] == 1
    assert (
        await c.get(
            f"/api/v1/technical/records?vehicle_id={uuid.uuid4()}", headers=stack.auth("manager")
        )
    ).json()["total"] == 0
    seen = await c.get("/api/v1/technical/records", headers=stack.auth("client"))
    assert seen.status_code == 200 and seen.json()["total"] == 1
    assert (
        await c.get("/api/v1/technical/records", headers=stack.auth("medic"))
    ).status_code == 403


async def test_export_by_record_ids(stack: Stack) -> None:
    """Выгрузка по явному списку записей."""
    first, second = (
        await _signed(stack),
        await _signed(stack, performed_at=(WHEN + timedelta(hours=1)).isoformat()),
    )
    export = await stack.client.post(
        "/api/v1/exports/medical",
        json={"organization_id": str(stack.world.org.id), "record_ids": [first, second]},
        headers=stack.auth("manager"),
    )
    assert export.status_code == 200 and export.content.startswith(b"%PDF")
    # Организация обязательна для менеджерских ролей: отчёт всегда по одной организации.
    no_org = await stack.client.post(
        "/api/v1/exports/medical", json={"record_ids": [first]}, headers=stack.auth("manager")
    )
    assert no_org.status_code == 422


async def test_ejournal_cancel_and_reject_release_records(stack: Stack) -> None:
    """Черновик отменяется, отклонённый журнал освобождает записи для нового журнала."""
    c, w = stack.client, stack.world
    rid = await _signed(stack)
    payload = {
        "kind": "medical",
        "organization_id": str(w.org.id),
        "period_from": "2026-10-14",
        "period_to": "2026-10-14",
    }

    draft = (await c.post("/api/v1/ejournals", json=payload, headers=stack.auth("manager"))).json()
    assert (
        await c.delete(f"/api/v1/ejournals/{draft['id']}", headers=stack.auth("manager"))
    ).status_code == 204
    assert (
        await c.get(f"/api/v1/ejournals/{draft['id']}", headers=stack.auth("manager"))
    ).status_code == 404

    journal = (
        await c.post("/api/v1/ejournals", json=payload, headers=stack.auth("manager"))
    ).json()
    submitted = await c.post(
        f"/api/v1/ejournals/{journal['id']}/submit", headers=stack.auth("manager")
    )
    assert submitted.json()["status"] == "awaiting_signature"
    reserved = (
        await c.get(f"/api/v1/medical/records/{rid}", headers=stack.auth("manager"))
    ).json()
    assert reserved["in_journal_reserved"] is True
    assert (
        await c.post(
            f"/api/v1/ejournals/{journal['id']}/reject",
            json={"reason": "x"},
            headers=stack.auth("manager"),
        )
    ).status_code == 403

    rejected = await c.post(
        f"/api/v1/ejournals/{journal['id']}/reject",
        json={"reason": "ошибка в данных"},
        headers=stack.auth("sa"),
    )
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert rejected.json()["reject_reason"] == "ошибка в данных"
    free = (await c.get(f"/api/v1/medical/records/{rid}", headers=stack.auth("manager"))).json()
    assert free["in_journal_reserved"] is False and free["status"] == "signed"
    again = await c.post("/api/v1/ejournals", json=payload, headers=stack.auth("manager"))
    assert again.status_code == 201 and again.json()["record_count"] == 1  # запись снова доступна


async def test_stats_shape_by_role(stack: Stack) -> None:
    """Плашки статистики: у медика только свои медосмотры, у менеджера ещё организации и водители."""
    c = stack.client
    await _signed(stack)
    await c.post(
        "/api/v1/medical/records", json=medical_body(stack.world), headers=stack.auth("medic")
    )  # неподписанная
    medic = (await c.get("/api/v1/stats/overview", headers=stack.auth("medic"))).json()
    assert medic["medical"] == {"to_sign": 1, "signed": 1, "total": 2}
    assert (
        medic["technical"] is None and medic["organizations"] is None and medic["drivers"] is None
    )
    mechanic = (await c.get("/api/v1/stats/overview", headers=stack.auth("mechanic"))).json()
    assert (
        mechanic["technical"] == {"to_sign": 0, "signed": 0, "total": 0}
        and mechanic["medical"] is None
    )
    manager = (await c.get("/api/v1/stats/overview", headers=stack.auth("manager"))).json()
    assert (
        set(manager["organizations"]) == {"active", "total"}
        and manager["organizations"]["total"] >= 1
    )
    assert set(manager["drivers"]) == {"active", "total"}
    assert manager["medical"]["total"] == 2 and manager["technical"] is not None
    assert (await c.get("/api/v1/stats/overview", headers=stack.auth("client"))).status_code == 403


async def test_me_shape(stack: Stack) -> None:
    """GET /me: профиль и права для построения интерфейса."""
    me = (await stack.client.get("/api/v1/me", headers=stack.auth("client"))).json()
    assert set(me) >= {"user_id", "role", "full_name", "organization_id", "permissions"}
    assert me["role"] == "client" and me["organization_id"] == str(stack.world.org.id)
    assert "medical:view_own_org" in me["permissions"] or any(
        "own_org" in p for p in me["permissions"]
    )


async def test_specialist_is_required_for_managers_and_signing_is_denied_to_them(
    stack: Stack,
) -> None:
    """Менеджер обязан указать специалиста и сам подписывать не может; специалист медосмотра — медик."""
    c, w = stack.client, stack.world
    manager = stack.auth("manager")
    missing = await c.post("/api/v1/medical/records", json=medical_body(w), headers=manager)
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "specialist_required"

    wrong = await c.post(
        "/api/v1/medical/records",
        json=medical_body(w, specialist_user_id=str(w.mechanic.id)),
        headers=manager,
    )
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "specialist_invalid"

    ok = await c.post(
        "/api/v1/medical/records",
        json=medical_body(w, specialist_user_id=str(w.medic.id)),
        headers=manager,
    )
    assert ok.status_code == 201 and ok.json()["specialist_user_id"] == str(w.medic.id)
    rid = ok.json()["id"]
    assert "sign" not in ok.json()["actions"]  # менеджеру кнопка «Подписать» не показывается
    denied = await c.post(
        "/api/v1/medical/records/sign", json={"record_ids": [rid]}, headers=manager
    )
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "permission_denied"

"""Проверка безопасности: доступ к чужим данным подменой идентификатора (IDOR) и утечки в ответах."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.domain.enums import WorkFormat
from app.models.catalog import Driver, Organization, Vehicle
from tests.http_stack import WHEN, Stack, medical_body, verified_user
from tests.integration.test_frontend_contract import _signed

pytestmark = pytest.mark.asyncio


async def _other_org(stack: Stack) -> dict[str, Any]:
    """Вторая организация (тоже на ЭПЛ) со своим водителем, ТС и подписанными записями."""
    async with stack.sessions() as session:
        org = Organization(
            id=uuid.uuid4(),
            inn="7736050003",
            name="ООО «Чужая»",
            work_format=WorkFormat.EPL,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        driver = Driver(
            id=uuid.uuid4(), organization_id=org.id, full_name="Чужой Водитель", is_active=True
        )
        vehicle = Vehicle(
            id=uuid.uuid4(),
            organization_id=org.id,
            brand="КАМАЗ",
            model="65115",
            plate="Х999ХХ99",
            is_active=True,
        )
        session.add_all([driver, vehicle])
        await session.commit()
        ids = {"org": org.id, "driver": driver.id, "vehicle": vehicle.id}
    med = await _signed(stack, organization_id=str(ids["org"]), driver_id=str(ids["driver"]))
    tech = await _signed(
        stack,
        "technical",
        "mechanic",
        organization_id=str(ids["org"]),
        vehicle_id=str(ids["vehicle"]),
    )
    stack.predreis.tokens["client_b"] = verified_user(uuid.uuid4(), "client", ids["org"])
    return ids | {"med": med, "tech": tech}


async def test_client_cannot_read_records_of_another_organization(stack: Stack) -> None:
    """Клиент организации А не видит запись организации Б ни по идентификатору, ни через фильтры."""
    other = await _other_org(stack)
    c, a = stack.client, stack.auth("client")
    assert (await c.get(f"/api/v1/medical/records/{other['med']}", headers=a)).status_code == 404
    assert (
        await c.get(f"/api/v1/technical/records/{other['tech']}", headers=a)
    ).status_code == 404
    listed = await c.get(f"/api/v1/medical/records?organization_id={other['org']}", headers=a)
    assert (
        listed.status_code == 200 and listed.json()["total"] == 0
    )  # фильтр не расширяет область видимости
    assert (
        other["med"] not in (await c.get("/api/v1/medical/records?page_size=100", headers=a)).text
    )
    by_driver = await c.get(f"/api/v1/medical/records?driver_id={other['driver']}", headers=a)
    assert by_driver.json()["total"] == 0
    # а клиент самой организации Б свою запись видит
    b = stack.auth("client_b")
    assert (await c.get(f"/api/v1/medical/records/{other['med']}", headers=b)).status_code == 200


async def test_client_cannot_export_or_download_foreign_data(stack: Stack) -> None:
    """Выгрузка по чужим записям или чужой организации не отдаёт данные организации Б."""
    other = await _other_org(stack)
    c, a = stack.client, stack.auth("client")
    by_ids = await c.post(
        "/api/v1/exports/medical", json={"record_ids": [other["med"]]}, headers=a
    )
    assert by_ids.status_code in (404, 422) or b"\xd0\xa7\xd1\x83\xd0\xb6" not in by_ids.content
    by_org = await c.post(
        "/api/v1/exports/medical", json={"organization_id": str(other["org"])}, headers=a
    )
    if by_org.status_code == 200:  # клиенту организация подставляется своя
        from io import BytesIO

        from pypdf import PdfReader

        text = "".join(p.extract_text() for p in PdfReader(BytesIO(by_org.content)).pages)
        assert "Чужая" not in text and "Чужой Водитель" not in text
    assert (await c.get("/api/v1/ejournals", headers=a)).status_code == 403


async def test_client_cannot_act_on_foreign_records(stack: Stack) -> None:
    """Клиенту недоступны изменения: ни своих, ни тем более чужих записей."""
    other = await _other_org(stack)
    c, a = stack.client, stack.auth("client")
    for method, path, body in (
        ("PATCH", f"/api/v1/medical/records/{other['med']}", {"pulse": 70}),
        ("DELETE", f"/api/v1/medical/records/{other['med']}", None),
        ("POST", f"/api/v1/medical/records/{other['med']}/deletion-request", {}),
        ("POST", "/api/v1/medical/records/sign", {"record_ids": [other["med"]]}),
        ("POST", "/api/v1/medical/records/delete", {"record_ids": [other["med"]]}),
        ("GET", f"/api/v1/catalog/drivers?organization_id={other['org']}", None),
        ("PATCH", f"/api/v1/catalog/organizations/{other['org']}", {"note": "x"}),
    ):
        resp = await c.request(method, path, json=body, headers=a)
        assert resp.status_code in (403, 404), (method, path, resp.status_code)


async def test_specialist_cannot_sign_or_edit_someone_elses_record(stack: Stack) -> None:
    """Медик не подписывает и не правит запись другого медика."""
    c = stack.client
    other_medic = uuid.uuid4()
    stack.predreis.tokens["medic_b"] = verified_user(other_medic, "medic")
    created = await c.post(
        "/api/v1/medical/records", json=medical_body(stack.world), headers=stack.auth("medic")
    )
    rid = created.json()["id"]
    b = stack.auth("medic_b")
    sign = await c.post("/api/v1/medical/records/sign", json={"record_ids": [rid]}, headers=b)
    assert sign.status_code == 200 and sign.json()["results"][0]["ok"] is False
    assert sign.json()["results"][0]["code"] == "not_record_specialist"
    patch = await c.patch(f"/api/v1/medical/records/{rid}", json={"pulse": 70}, headers=b)
    assert patch.status_code == 403 and patch.json()["error"]["code"] == "not_record_specialist"
    for method, path in (
        ("DELETE", f"/api/v1/medical/records/{rid}"),
        ("POST", f"/api/v1/medical/records/{rid}/clear-note"),
    ):
        resp = await c.request(method, path, headers=b)
        assert resp.status_code == 403, (method, resp.text)
    seen = (await c.get(f"/api/v1/medical/records/{rid}", headers=b)).json()
    assert seen["actions"] == []  # чужой медик видит запись, но кнопок у него нет
    batch = await c.post("/api/v1/medical/records/delete", json={"record_ids": [rid]}, headers=b)
    assert batch.json()["results"][0]["code"] == "not_record_specialist"
    own = (await c.get(f"/api/v1/medical/records/{rid}", headers=stack.auth("medic"))).json()
    assert {"edit", "delete", "sign"} <= set(own["actions"])  # свой медик — может всё
    manager = await c.patch(
        f"/api/v1/medical/records/{rid}", json={"pulse": 71}, headers=stack.auth("manager")
    )
    assert manager.status_code == 200  # менеджерские роли правят любые неподписанные записи


async def test_unknown_ids_do_not_reveal_existence(stack: Stack) -> None:
    """Чужая и несуществующая запись отвечают одинаково: по ответу нельзя узнать, что запись есть."""
    other = await _other_org(stack)
    c, a = stack.client, stack.auth("client")
    foreign = await c.get(f"/api/v1/medical/records/{other['med']}", headers=a)
    missing = await c.get(f"/api/v1/medical/records/{uuid.uuid4()}", headers=a)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


async def test_errors_do_not_leak_internals(stack: Stack) -> None:
    """Ответ 422 не раскрывает SQL и стек; некорректный JSON — обычная ошибка формата."""
    c, h = stack.client, stack.auth("manager")
    bad = await c.get("/api/v1/medical/records/not-a-uuid", headers=h)
    assert (
        bad.status_code == 422
        and "Traceback" not in bad.text
        and "sqlalchemy" not in bad.text.lower()
    )
    broken = await c.post(
        "/api/v1/medical/records",
        content=b"{not json",
        headers=h | {"content-type": "application/json"},
    )
    assert broken.status_code == 422 and "Traceback" not in broken.text
    assert WHEN  # константа используется в соседних тестах; импорт оставлен для единообразия

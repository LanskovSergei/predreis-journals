"""Пункты ТЗ, закрытые без внешних зависимостей: поиск ТС, пакетное удаление, стандартное время,
сортировка каталога, проверка даты рождения, раскладка PDF."""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy import update

from app.models.catalog import Driver, Organization
from tests.http_stack import WHEN, Stack, medical_body
from tests.integration.test_frontend_contract import _signed

pytestmark = pytest.mark.asyncio


def tech_body(stack: Stack, **over: object) -> dict[str, object]:
    """Тело записи техконтроля."""
    w = stack.world
    return {
        "organization_id": str(w.org.id),
        "vehicle_id": str(w.vehicle.id),
        "performed_at": WHEN.isoformat(),
        "odometer": 1000,
        "result": "admitted",
    } | over


async def test_vehicle_search_by_brand_model_and_plate(stack: Stack) -> None:
    """Фильтр архива техконтроля «марка + модель + госномер» (ТЗ, стр. 5, п. 15)."""
    c, h = stack.client, stack.auth("mechanic")
    assert (
        await c.post("/api/v1/technical/records", json=tech_body(stack), headers=h)
    ).status_code == 201
    for query, found in (
        ("газон", 1),
        ("ГАЗон Next", 1),
        ("О224ЕК", 1),
        ("next о224", 1),
        ("камаз", 0),
        ("Next ГАЗон", 0),
    ):
        page = (
            await c.get("/api/v1/technical/records", params={"vehicle": query}, headers=h)
        ).json()
        assert page["total"] == found, query
    assert (
        await c.get("/api/v1/technical/records?vehicle=га", headers=h)
    ).status_code == 422  # от 3 символов


async def test_batch_delete_reports_each_record(stack: Stack) -> None:
    """«Удалить выбранные» (ТЗ, стр. 7): неподписанные удаляются, подписанные и чужие — отказ по каждой."""
    c, w = stack.client, stack.world
    medic = stack.auth("medic")
    plain = [
        (
            await c.post(
                "/api/v1/medical/records",
                json=medical_body(w, performed_at=(WHEN + timedelta(hours=i)).isoformat()),
                headers=medic,
            )
        ).json()["id"]
        for i in range(2)
    ]
    signed = await _signed(stack, performed_at=(WHEN + timedelta(hours=5)).isoformat())
    missing = str(uuid.uuid4())
    result = await c.post(
        "/api/v1/medical/records/delete",
        json={"record_ids": [*plain, signed, missing, plain[0]]},
        headers=medic,
    )
    assert result.status_code == 200
    data = result.json()
    assert (data["deleted"], data["failed"]) == (2, 2) and len(
        data["results"]
    ) == 4  # повтор схлопнут
    by_id = {r["record_id"]: r for r in data["results"]}
    assert by_id[signed]["code"] in {"record_immutable", "invalid_status"}
    assert by_id[missing]["code"] == "not_found"
    for rid in plain:
        assert (await c.get(f"/api/v1/medical/records/{rid}", headers=medic)).status_code == 404
    assert (await c.get(f"/api/v1/medical/records/{signed}", headers=medic)).json()[
        "status"
    ] == "signed"

    assert (
        await c.post(
            "/api/v1/medical/records/delete",
            json={"record_ids": [signed]},
            headers=stack.auth("client"),
        )
    ).status_code == 403
    too_many = await c.post(
        "/api/v1/medical/records/delete",
        json={"record_ids": [str(uuid.uuid4()) for _ in range(51)]},
        headers=medic,
    )
    assert too_many.status_code == 400


async def test_standard_time_is_taken_from_the_last_paper_record(stack: Stack) -> None:
    """«Стандартное время» (ТЗ, стр. 9, 11): первая запись — вручную, дальше подставляется прежнее время."""
    c, w = stack.client, stack.world
    medic = stack.auth("medic")
    empty = (
        await c.get(
            f"/api/v1/medical/records/standard-time?driver_id={w.driver.id}", headers=medic
        )
    ).json()
    assert empty == {"time": None, "performed_at": None, "record_id": None}

    await c.post(
        "/api/v1/medical/records", json=medical_body(w), headers=medic
    )  # 08:20, предрейсовый
    later = (WHEN + timedelta(days=1)).replace(hour=19, minute=5)
    await c.post(
        "/api/v1/medical/records",
        json=medical_body(w, phase="post", performed_at=later.isoformat()),
        headers=medic,
    )

    last = (
        await c.get(
            f"/api/v1/medical/records/standard-time?driver_id={w.driver.id}", headers=medic
        )
    ).json()
    assert last["time"] == "19:05"
    pre = (
        await c.get(
            f"/api/v1/medical/records/standard-time?driver_id={w.driver.id}&phase=pre",
            headers=medic,
        )
    ).json()
    assert pre["time"] == "08:20"  # у предрейсового и послерейсового своё время
    other = (
        await c.get(
            f"/api/v1/medical/records/standard-time?driver_id={uuid.uuid4()}", headers=medic
        )
    ).json()
    assert other["time"] is None

    mech = stack.auth("mechanic")
    await c.post(
        "/api/v1/technical/records",
        json=tech_body(stack, performed_at=WHEN.replace(hour=7, minute=45).isoformat()),
        headers=mech,
    )
    tech = (
        await c.get(
            f"/api/v1/technical/records/standard-time?vehicle_id={w.vehicle.id}", headers=mech
        )
    ).json()
    assert tech["time"] == "07:45"
    assert (
        await c.get(
            f"/api/v1/medical/records/standard-time?driver_id={w.driver.id}",
            headers=stack.auth("client"),
        )
    ).status_code == 403


async def test_catalog_is_sorted_without_legal_form(stack: Stack) -> None:
    """Каталог организаций по алфавиту без правовой формы и кавычек (ТЗ, стр. 15)."""
    names = [
        "Общество с ограниченной ответственностью «Юпитер»",
        "ИП Абрамов Алексей Иванович",
        "АО «Вега»",
        "ПАО Бета",
        "ООО «Гамма»",
    ]
    async with stack.sessions() as session:
        for i, name in enumerate(names):
            session.add(
                Organization(
                    id=uuid.uuid4(), inn=f"77{i:08d}", name=name, short_name=name, is_active=True
                )
            )
        await session.commit()
    items = (
        await stack.client.get(
            "/api/v1/catalog/organizations?page_size=50", headers=stack.auth("manager")
        )
    ).json()["items"]
    ours = [o["name"] for o in items if o["name"] in names]
    assert ours == [
        "ИП Абрамов Алексей Иванович",
        "ПАО Бета",
        "АО «Вега»",
        "ООО «Гамма»",
        "Общество с ограниченной ответственностью «Юпитер»",
    ]


async def test_disputed_birth_date_adds_a_note_when_record_is_created(stack: Stack) -> None:
    """Спорная дата рождения водителя (ТЗ, стр. 5, п. 12): сервис ставит метку в «Примечание», подписать нельзя."""
    w = stack.world
    async with stack.sessions() as session:
        await session.execute(
            update(Driver).where(Driver.id == w.driver.id).values(birth_date=date(2012, 3, 1))
        )
        await session.commit()
    created = (
        await stack.client.post(
            "/api/v1/medical/records", json=medical_body(w), headers=stack.auth("medic")
        )
    ).json()
    assert created["has_note"] is True and "дату рождения" in created["note"]
    assert "sign" not in created["actions"] and "clear_note" in created["actions"]


async def test_export_is_landscape_ordered_and_rows_are_not_split(stack: Stack) -> None:
    """Выгрузка (ТЗ, стр. 19-20): альбомная, строки от ранней даты, строка не разрывается между страницами."""
    c, w = stack.client, stack.world
    for hour in (10, 8, 9):  # создаём не по порядку
        await _signed(stack, performed_at=WHEN.replace(hour=hour, minute=0).isoformat())
    for minute in range(1, 40):  # ещё строки, чтобы документ занял несколько страниц
        await _signed(stack, performed_at=WHEN.replace(hour=11, minute=minute).isoformat())
    pdf = await c.post(
        "/api/v1/exports/medical",
        json={
            "organization_id": str(w.org.id),
            "date_from": "2026-10-14",
            "date_to": "2026-10-14",
        },
        headers=stack.auth("manager"),
    )
    reader = PdfReader(BytesIO(pdf.content))
    box = reader.pages[0].mediabox
    assert float(box.width) > float(box.height)  # альбомная
    assert len(reader.pages) > 1
    text = "\n".join(p.extract_text() for p in reader.pages)
    assert text.index("08:00") < text.index("09:00") < text.index("10:00") < text.index("11:01")
    rows = 0
    for page in reader.pages:
        page_text = page.extract_text()
        # Время осмотра (ЧЧ:ММ) есть только в строках таблицы; в заголовке первой страницы его нет.
        times = len(re.findall(r"\b\d{2}:\d{2}\b", page_text))
        validity = page_text.count("Действителен")
        assert times == validity, "строка разорвана между страницами"
        rows += times
    assert rows == 42

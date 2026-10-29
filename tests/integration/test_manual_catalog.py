"""Ручной каталог (решение заказчика): бумажные клиенты, водители и ТС гибридных клиентов, объединение
с платформой по реквизитам и привязка событий ЭПЛ к объединённым карточкам."""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.enums import CatalogOrigin, WorkFormat
from app.integrations.predreis.schemas import DriverPayload, OrganizationPayload, VehiclePayload
from app.models.audit import AuditLog
from app.models.catalog import Driver, Organization, Vehicle
from app.models.records import MedicalRecord
from app.modules.catalog.service import upsert_driver, upsert_organization, upsert_vehicle
from app.workers.consumer import Outcome, process_body
from tests.factories import seed
from tests.http_stack import Stack, medical_body
from tests.integration.test_consumer_and_sync import body, exam_payload, factory

pytestmark = pytest.mark.asyncio
SNILS = "112-233-445 95"  # корректное контрольное число


def make_inn(prefix9: str) -> str:
    """ИНН организации с верным контрольным разрядом."""
    weights = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    return prefix9 + str(sum(w * int(d) for w, d in zip(weights, prefix9, strict=True)) % 11 % 10)


def org_body(**over: Any) -> dict[str, Any]:
    """Тело новой организации."""
    return {
        "inn": make_inn("770000001"),
        "name": "ООО «Бумажный клиент»",
        "short_name": "Бумажный",
    } | over


async def test_manual_organization_lifecycle(stack: Stack) -> None:
    """Организация добавляется вручную, видна в общем каталоге с пометкой «вручную», правится и удаляется."""
    c, h = stack.client, stack.auth("manager")
    created = await c.post("/api/v1/catalog/organizations", json=org_body(), headers=h)
    assert created.status_code == 201, created.text
    org = created.json()
    assert org["origin"] == "manual" and org["work_format"] == "paper"
    assert org["contract_until"] == "2026-12-31"  # ТЗ: срок договора по умолчанию

    listed = (await c.get("/api/v1/catalog/organizations?page_size=50", headers=h)).json()["items"]
    origins = {o["id"]: o["origin"] for o in listed}
    assert (
        origins[org["id"]] == "manual" and origins[str(stack.world.org.id)] == "platform"
    )  # общий каталог
    only_manual = (await c.get("/api/v1/catalog/organizations?origin=manual", headers=h)).json()
    assert [o["id"] for o in only_manual["items"]] == [org["id"]]

    renamed = await c.patch(
        f"/api/v1/catalog/organizations/{org['id']}",
        json={"name": "ООО «Новое имя»", "contract_type": "medtech"},
        headers=h,
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "ООО «Новое имя»"
    assert (
        await c.delete(f"/api/v1/catalog/organizations/{org['id']}", headers=h)
    ).status_code == 204
    assert (
        await c.patch(f"/api/v1/catalog/organizations/{org['id']}", json={"note": "x"}, headers=h)
    ).status_code == 404


async def test_inn_is_validated_and_unique(stack: Stack) -> None:
    """ИНН проверяется по контрольному разряду; одна организация — одна карточка во всём каталоге."""
    c, h = stack.client, stack.auth("manager")
    bad = await c.post("/api/v1/catalog/organizations", json=org_body(inn="7707083894"), headers=h)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "request_invalid"
    dup = await c.post(
        "/api/v1/catalog/organizations", json=org_body(inn=stack.world.org.inn), headers=h
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "organization_exists"
    assert dup.json()["error"]["details"]["organization_id"] == str(stack.world.org.id)
    ip = await c.post(
        "/api/v1/catalog/organizations",
        json=org_body(inn="500100732259", name="ИП Петров"),
        headers=h,
    )
    assert ip.status_code == 201  # ИНН ИП, 12 цифр


async def test_drivers_and_vehicles_can_be_added_to_any_organization(stack: Stack) -> None:
    """Водители и ТС вручную: и к ручной организации, и к организации из платформы (гибридный клиент)."""
    c, h, w = stack.client, stack.auth("manager"), stack.world
    manual = (await c.post("/api/v1/catalog/organizations", json=org_body(), headers=h)).json()
    drivers = await c.post(
        "/api/v1/catalog/drivers",
        json={"drivers": [
            {"organization_id": manual["id"], "full_name": "Бумажный Иван Иванович", "birth_date": "1980-05-05", "snils": SNILS},
            {"organization_id": str(w.org.id), "full_name": "Гибридов Пётр Петрович", "birth_date": "1985-01-01"},
        ]},
        headers=h,
    )  # fmt: skip
    assert drivers.status_code == 201, drivers.text
    assert [d["origin"] for d in drivers.json()] == ["manual", "manual"]
    vehicles = await c.post(
        "/api/v1/catalog/vehicles",
        json={"vehicles": [{"organization_id": str(w.org.id), "brand": "ГАЗель", "model": "Next", "plate": "a 123 bc 77"}]},
        headers=h,
    )  # fmt: skip
    assert (
        vehicles.status_code == 201 and vehicles.json()[0]["plate"] == "А123ВС77"
    )  # латиница → кириллица

    too_many = {
        "drivers": [
            {"organization_id": manual["id"], "full_name": f"Водитель Номер {i}"}
            for i in range(11)
        ]
    }
    assert (
        await c.post("/api/v1/catalog/drivers", json=too_many, headers=h)
    ).status_code == 422  # ТЗ: до 10
    bad_snils = {
        "drivers": [
            {
                "organization_id": manual["id"],
                "full_name": "Ошибкин Олег",
                "snils": "112-233-445 96",
            }
        ]
    }
    assert (await c.post("/api/v1/catalog/drivers", json=bad_snils, headers=h)).status_code == 422
    dup_driver = {
        "drivers": [
            {
                "organization_id": manual["id"],
                "full_name": "бумажный иван иванович",
                "birth_date": "1980-05-05",
            }
        ]
    }
    resp = await c.post("/api/v1/catalog/drivers", json=dup_driver, headers=h)
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "driver_exists"
    dup_plate = {
        "vehicles": [
            {"organization_id": str(w.org.id), "brand": "Х", "model": "Y", "plate": "о 224 ек 790"}
        ]
    }
    resp = await c.post("/api/v1/catalog/vehicles", json=dup_plate, headers=h)
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "vehicle_exists"
    # всё или ничего: вторая строка с ошибкой — первая тоже не сохраняется
    mixed = {"drivers": [
        {"organization_id": manual["id"], "full_name": "Новый Николай Н."},
        {"organization_id": manual["id"], "full_name": "Бумажный Иван Иванович", "birth_date": "1980-05-05"},
    ]}  # fmt: skip
    assert (await c.post("/api/v1/catalog/drivers", json=mixed, headers=h)).status_code == 409
    names = [
        d["full_name"]
        for d in (
            await c.get(f"/api/v1/catalog/drivers?organization_id={manual['id']}", headers=h)
        ).json()["items"]
    ]
    assert "Новый Николай Н." not in names


async def test_platform_cards_keep_platform_fields(stack: Stack) -> None:
    """Реквизиты из ПРЕДРЕЙС в журналах не меняются; поля журналов (договор, СНИЛС, примечание) — да."""
    c, h, w = stack.client, stack.auth("manager"), stack.world
    locked = await c.patch(
        f"/api/v1/catalog/organizations/{w.org.id}", json={"name": "Другое имя"}, headers=h
    )
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "managed_by_predreis"
    assert locked.json()["error"]["details"]["fields"] == ["name"]
    ok = await c.patch(
        f"/api/v1/catalog/organizations/{w.org.id}",
        json={"contract_number": "Д-15", "note": "звонить утром"},
        headers=h,
    )
    assert ok.status_code == 200 and ok.json()["contract_number"] == "Д-15"
    assert (
        await c.patch(
            f"/api/v1/catalog/drivers/{w.driver.id}", json={"full_name": "Иной Иван"}, headers=h
        )
    ).status_code == 409
    assert (
        await c.patch(f"/api/v1/catalog/drivers/{w.driver.id}", json={"snils": SNILS}, headers=h)
    ).json()["snils"] == SNILS
    assert (
        await c.patch(
            f"/api/v1/catalog/vehicles/{w.vehicle.id}", json={"plate": "А000АА77"}, headers=h
        )
    ).status_code == 409
    assert (
        await c.patch(
            f"/api/v1/catalog/vehicles/{w.vehicle.id}",
            json={"diag_card_until": "2027-01-01"},
            headers=h,
        )
    ).status_code == 200
    assert (await c.delete(f"/api/v1/catalog/organizations/{w.org.id}", headers=h)).json()[
        "error"
    ]["code"] == "managed_by_predreis"


async def test_records_for_manual_catalog_and_delete_rules(stack: Stack) -> None:
    """По ручным карточкам ведутся записи; карточку с записями не удалить — только сделать неактивной."""
    c, h = stack.client, stack.auth("manager")
    org = (await c.post("/api/v1/catalog/organizations", json=org_body(), headers=h)).json()
    driver = (
        await c.post(
            "/api/v1/catalog/drivers",
            json={
                "drivers": [
                    {
                        "organization_id": org["id"],
                        "full_name": "Бумажный Иван Иванович",
                        "birth_date": "1980-05-05",
                    }
                ]
            },
            headers=h,
        )
    ).json()[0]
    spare = (
        await c.post(
            "/api/v1/catalog/vehicles",
            json={
                "vehicles": [
                    {
                        "organization_id": org["id"],
                        "brand": "УАЗ",
                        "model": "Патриот",
                        "plate": "Е777КХ77",
                    }
                ]
            },
            headers=h,
        )
    ).json()[0]

    body_ = medical_body(stack.world, organization_id=org["id"], driver_id=driver["id"])
    record = await c.post("/api/v1/medical/records", json=body_, headers=stack.auth("medic"))
    assert record.status_code == 201, record.text
    assert record.json()["snapshot"]["organization"]["inn"] == org["inn"]

    assert (await c.delete(f"/api/v1/catalog/drivers/{driver['id']}", headers=h)).json()["error"][
        "code"
    ] == "in_use"
    assert (await c.delete(f"/api/v1/catalog/organizations/{org['id']}", headers=h)).json()[
        "error"
    ]["code"] == "in_use"
    assert (
        await c.delete(f"/api/v1/catalog/vehicles/{spare['id']}", headers=h)
    ).status_code == 204  # без записей
    off = await c.patch(
        f"/api/v1/catalog/drivers/{driver['id']}", json={"is_active": False}, headers=h
    )
    assert off.status_code == 200 and off.json()["is_active"] is False


async def test_only_manager_roles_manage_the_catalog(stack: Stack) -> None:
    """Добавлять и править каталог могут Предрейс, Админ, СА (ТЗ: «Добавить организацию/водителя/авто»)."""
    for who, status in (
        ("medic", 403),
        ("mechanic", 403),
        ("client", 403),
        ("admin", 201),
        ("sa", 201),
    ):
        inn = make_inn(f"77000{who.__len__():02d}{len(who)}{'1' if who == 'sa' else '2'}")
        resp = await stack.client.post(
            "/api/v1/catalog/organizations", json=org_body(inn=inn), headers=stack.auth(who)
        )
        assert resp.status_code == status, (who, resp.text)


async def test_sync_links_manual_cards_and_epl_events_bind_to_them(
    session: AsyncSession, storage: Any
) -> None:
    """Бумажный клиент приходит на платформу: карточки объединяются по реквизитам, наш id и записи сохраняются,
    поля журналов не теряются, а события ЭПЛ с идентификаторами Предрейса попадают на объединённые карточки."""
    w = await seed(session)
    inn = make_inn("771111111")
    org = Organization(id=uuid.uuid4(), origin=CatalogOrigin.MANUAL, work_format=WorkFormat.PAPER, inn=inn,
                       name="ООО «Был на бумаге»", contract_number="Д-1", is_active=True)  # fmt: skip
    driver = Driver(id=uuid.uuid4(), origin=CatalogOrigin.MANUAL, organization_id=org.id, is_active=True,
                    full_name="Ефимов Андрей Константинович", birth_date=date(1980, 1, 1), snils=SNILS)  # fmt: skip
    vehicle = Vehicle(id=uuid.uuid4(), origin=CatalogOrigin.MANUAL, organization_id=org.id, is_active=True,
                      brand="ГАЗон", model="Next", plate="О224ЕК790")  # fmt: skip
    session.add(org)
    await session.flush()
    session.add_all([driver, vehicle])
    await session.commit()
    org_id, driver_id, vehicle_id = org.id, driver.id, vehicle.id  # до expire_all

    p_org, p_drv, p_veh = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await upsert_organization(
        session,
        OrganizationPayload.model_validate(
            {"id": str(p_org), "inn": inn, "name_full": "ООО «Теперь на ЭПЛ»"}
        ),
    )
    await upsert_driver(
        session,
        DriverPayload.model_validate(
            {
                "id": str(p_drv),
                "org_id": str(p_org),
                "full_name": "ЕФИМОВ Андрей Константинович",
                "birth_date": "1980-01-01",
            }
        ),
    )
    await upsert_vehicle(
        session,
        VehiclePayload.model_validate(
            {
                "id": str(p_veh),
                "org_id": str(p_org),
                "plate_number": "o224ek790",
                "brand": "ГАЗон",
                "model": "Next",
            }
        ),
    )
    await session.commit()
    session.expire_all()

    merged = await session.get(Organization, org_id)
    assert (
        merged is not None
        and merged.predreis_id == p_org
        and merged.origin is CatalogOrigin.PLATFORM
    )
    assert (
        merged.work_format is WorkFormat.EPL and merged.name == "ООО «Теперь на ЭПЛ»"
    )  # реквизиты из платформы
    assert merged.contract_number == "Д-1"  # поле журналов сохранено
    assert await session.get(Organization, p_org) is None  # второй карточки нет
    d = await session.get(Driver, driver_id)
    assert d is not None and d.predreis_id == p_drv and d.snils == SNILS
    v = await session.get(Vehicle, vehicle_id)
    assert v is not None and v.predreis_id == p_veh
    linked = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "catalog.linked")))
        .scalars()
        .all()
    )
    assert sorted(a.entity_type for a in linked) == ["driver", "organization", "vehicle"]

    ns = SimpleNamespace(org=SimpleNamespace(id=p_org, inn=inn), driver=SimpleNamespace(id=p_drv),
                         vehicle=SimpleNamespace(id=p_veh), medic=w.medic, mechanic=w.mechanic)  # fmt: skip
    event = exam_payload(ns)
    # реквизиты в событии намеренно не совпадают: привязка обязана идти по идентификаторам Предрейса
    event["organization"]["inn"] = make_inn("779999999")
    event["driver"]["last_name"] = "Другая-Фамилия"
    outcome = await process_body(body(event), factory(session), storage, Settings())
    assert outcome is Outcome.ACK
    rec = (await session.execute(select(MedicalRecord))).scalar_one()
    assert (rec.organization_id, rec.driver_id) == (
        org_id,
        driver_id,
    )  # событие попало на объединённые карточки


async def test_ambiguous_manual_cards_are_not_linked(session: AsyncSession) -> None:
    """Два ручных тёзки без даты рождения: объединение не угадывает, создаётся отдельная карточка платформы."""
    await seed(session)
    inn = make_inn("772222222")
    org = Organization(
        id=uuid.uuid4(),
        origin=CatalogOrigin.MANUAL,
        work_format=WorkFormat.PAPER,
        inn=inn,
        name="ООО Тёзки",
        is_active=True,
    )
    session.add(org)
    await session.flush()
    session.add_all(
        [
            Driver(
                id=uuid.uuid4(),
                origin=CatalogOrigin.MANUAL,
                organization_id=org.id,
                full_name="Иванов Иван",
                is_active=True,
            )
            for _ in range(2)
        ]
    )
    await session.commit()
    p_org, p_drv = uuid.uuid4(), uuid.uuid4()
    await upsert_organization(
        session,
        OrganizationPayload.model_validate(
            {"id": str(p_org), "inn": inn, "name_full": "ООО Тёзки"}
        ),
    )
    await upsert_driver(
        session,
        DriverPayload.model_validate(
            {"id": str(p_drv), "org_id": str(p_org), "full_name": "Иванов Иван"}
        ),
    )
    await session.commit()
    drivers = (
        (await session.execute(select(Driver).where(Driver.organization_id == org.id)))
        .scalars()
        .all()
    )
    assert len(drivers) == 3 and sum(d.origin is CatalogOrigin.MANUAL for d in drivers) == 2


@pytest.mark.parametrize(("flag", "expected"), [(True, WorkFormat.EPL), (False, WorkFormat.PAPER)])
async def test_work_format_follows_platform_epl_ready_flag(
    session: AsyncSession, flag: bool, expected: WorkFormat
) -> None:
    """Значок «на ЭПЛ / на бумаге» по данным платформы: реквизиты для ЭПЛ и МЧД оформлены или нет."""
    await seed(session)
    pid = uuid.uuid4()
    payload = {
        "id": str(pid),
        "inn": make_inn("773333333"),
        "name_full": "ООО Флаг",
        "epl_ready": flag,
    }
    await upsert_organization(session, OrganizationPayload.model_validate(payload))
    await session.commit()
    org = await session.get(Organization, pid)
    assert org is not None and org.work_format is expected


async def test_epl_ready_changes_are_synced_and_absent_flag_changes_nothing(
    session: AsyncSession,
) -> None:
    """Организация прошла МЧД — становится «на ЭПЛ»; признак не прислан — формат не меняется."""
    await seed(session)
    pid, inn = uuid.uuid4(), make_inn("774444444")
    base = {"id": str(pid), "inn": inn, "name_full": "ООО Переход"}
    for flag, expected in (
        (False, WorkFormat.PAPER),
        (None, WorkFormat.PAPER),
        (True, WorkFormat.EPL),
    ):
        data = base | ({"epl_ready": flag} if flag is not None else {})
        await upsert_organization(session, OrganizationPayload.model_validate(data))
        await session.commit()
        session.expire_all()
        org = await session.get(Organization, pid)
        assert org is not None and org.work_format is expected, flag


async def test_manual_client_registered_without_mchd_stays_on_paper(session: AsyncSession) -> None:
    """Бумажный клиент зарегистрировался в ПРЕДРЕЙС, но МЧД ещё не оформил: карточка объединена, но «на бумаге»."""
    await seed(session)
    inn = make_inn("775555555")
    org = Organization(
        id=uuid.uuid4(),
        origin=CatalogOrigin.MANUAL,
        work_format=WorkFormat.PAPER,
        inn=inn,
        name="ООО Без МЧД",
        is_active=True,
    )
    session.add(org)
    await session.commit()
    org_id = org.id
    pid = uuid.uuid4()
    await upsert_organization(
        session,
        OrganizationPayload.model_validate(
            {"id": str(pid), "inn": inn, "name_full": "ООО Без МЧД", "epl_ready": False}
        ),
    )
    await session.commit()
    session.expire_all()
    merged = await session.get(Organization, org_id)
    assert (
        merged is not None
        and merged.predreis_id == pid
        and merged.origin is CatalogOrigin.PLATFORM
    )
    assert merged.work_format is WorkFormat.PAPER  # клиенты организации журналы пока не видят

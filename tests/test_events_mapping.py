"""Сообщения очереди Предрейса (реальные образцы от 25.10.2026) → нормализованное событие."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from app.integrations.predreis.events import (
    Envelope,
    UnmappableEventError,
    map_envelope,
    message_uuid,
    pick,
)
from app.integrations.predreis.schemas import DriverPayload, OrganizationPayload, VehiclePayload
from tests.samples.predreis import load


def envelope(name: str, **payload_changes: Any) -> Envelope:
    """Конверт из образца; изменения применяются к payload (None удаляет поле)."""
    raw = load(name)
    for key, value in payload_changes.items():
        if value is None:
            raw["payload"].pop(key, None)
        else:
            raw["payload"][key] = value
    return Envelope.model_validate(raw)


def test_real_pre_trip_event() -> None:
    """Предрейсовый осмотр «Водитель+»: ИП без адреса и КПП, пол неизвестен, права одним номером."""
    ev = map_envelope(envelope("event_medical_pre.json"))
    assert ev.event_type == "T2"
    assert ev.event_id == uuid.UUID("0b2b9f64-3e8c-4a55-9f1a-2c4d6e8a1b33")
    assert ev.waybill_number == "AE5CA99A" and ev.edweb_document_id == "1458084322"
    assert (ev.org_inn, ev.org_kpp, ev.org_ogrn) == ("770000000000", None, "300000000000000")
    assert ev.org_name == "Индивидуальный предприниматель Иванов Иван Иванович"
    assert ev.org_short_name == "ИП ИВАНОВ ИВАН ИВАНОВИЧ" and ev.org_address is None
    assert ev.organization_id == uuid.UUID("83770066-a33c-4894-8cfc-90eef5e086da")
    assert ev.driver_id == uuid.UUID("bd8a9b05-c07c-4aa7-9f73-3ef2924d41ec")
    assert ev.driver_full_name == "Петров Пётр Петрович" and ev.driver_gender is None
    assert ev.driver_birth_date == date(2000, 9, 9) and ev.license_text == "9900000000"
    assert ev.specialist_user_id == uuid.UUID("32b933cf-f31a-4e55-b0be-39a221a64ed7")
    assert ev.specialist_full_name == "Сидорова Анна Сергеевна"
    assert ev.exam_datetime == datetime(2026, 9, 25, 9, 20, 32, 859899, tzinfo=timezone.utc)
    assert (ev.blood_pressure_systolic, ev.blood_pressure_diastolic, ev.pulse) == (116, 80, 78)
    assert ev.temperature == Decimal("36.5") and ev.alcohol_ppm == Decimal("0.0")
    assert ev.alcohol_detected is False and ev.complaints == "отсутствуют"
    assert ev.approved is True and ev.critical_flag is False
    assert ev.notes == "Автоматический предрейсовый осмотр (Водитель+)"


def test_automatic_exam_has_unknown_harmful_factors_and_is_accepted() -> None:
    """У «Водителя+» признак вредных факторов не определяется (null) — запись всё равно создаётся."""
    ev = map_envelope(envelope("event_medical_pre.json"))
    assert ev.harmful_factors_detected is None and ev.harmful_factors is None


def test_real_post_trip_event() -> None:
    """Послерейсовый осмотр — Т6, другой специалист, другое давление."""
    ev = map_envelope(envelope("event_medical_post.json"))
    assert ev.event_type == "T6" and ev.blood_pressure_diastolic == 90
    assert ev.specialist_full_name == "Кузнецова Мария Ивановна"
    assert ev.waybill_id == uuid.UUID("ae5ca99a-5ae4-413e-85a9-1ceffefb285d")


def test_old_technical_event_without_time_is_parked_with_clear_reason() -> None:
    """Образец техконтроля: `exam_datetime` = null (старая запись) — время не выдумываем."""
    with pytest.raises(UnmappableEventError) as exc:
        map_envelope(envelope("event_technical.json"))
    assert exc.value.reason == "exam_time_missing"


def test_technical_event_with_time() -> None:
    """У новых записей время заполнено: Т3, проверки систем, одометр, ТС по номеру `plate_number`."""
    ev = map_envelope(envelope("event_technical.json", exam_datetime="2026-10-25T08:36:00+00:00"))
    assert ev.event_type == "T3" and ev.odometer == 11880 and ev.approved is True
    assert (ev.brakes_ok, ev.lighting_ok, ev.tires_ok) == (True, True, True)
    assert ev.vehicle_plate == "О231ТА790" and ev.vehicle_category == "B"
    assert ev.vehicle_brand == "VOLKSWAGEN" and ev.vehicle_model == "TOURAN"
    assert ev.vehicle_id == uuid.UUID("26a36da0-8699-4324-9d83-17e58ee8f7e4")
    assert ev.specialist_full_name == "Механиков Дмитрий Юрьевич"


@pytest.mark.parametrize(
    ("series", "number", "expected"),
    [
        ("9910", "915125", "9910 915125"),  # серия и номер раздельно
        (None, "9910 915125", "9910 915125"),  # серия внутри номера — как есть
        (None, "9900000000", "9900000000"),
    ],
)
def test_license_is_kept_as_text(series: str | None, number: str, expected: str) -> None:
    """Права одной строкой: серия и номер не разбираются автоматически, но и не теряются."""
    raw = load("event_medical_pre.json")
    raw["payload"]["driver"].update(license_series=series, license_number=number)
    assert map_envelope(Envelope.model_validate(raw)).license_text == expected


@pytest.mark.parametrize("gender", ["M", "F"])
def test_driver_gender_when_present(gender: str) -> None:
    """Пол «M»/«F» принимается."""
    raw = load("event_medical_pre.json")
    raw["payload"]["driver"]["gender"] = gender
    ev = map_envelope(Envelope.model_validate(raw))
    assert ev.driver_gender is not None and ev.driver_gender.value == gender


@pytest.mark.parametrize(
    ("changes", "title"),
    [
        ({"exam_type": "pre_trip", "title_number": 2}, "T2"),
        ({"exam_type": "post_trip", "title_number": 6}, "T6"),
        ({"exam_type": "post_trip", "title_number": None}, "T6"),
        ({"exam_type": None, "title_number": 2}, "T2"),
    ],
)
def test_phase_from_exam_type_and_title_number(changes: dict[str, Any], title: str) -> None:
    """Фаза определяется по exam_type и/или title_number; одного признака достаточно."""
    assert map_envelope(envelope("event_medical_pre.json", **changes)).event_type == title


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"exam_type": "post_trip", "title_number": 2}, "title_conflict"),
        ({"exam_type": "during_trip"}, "exam_type_unknown"),
        ({"title_number": 3}, "title_mismatch"),
        ({"exam_type": None, "title_number": None}, "phase_unknown"),
    ],
)
def test_contradictory_or_missing_phase_is_rejected(changes: dict[str, Any], reason: str) -> None:
    """Противоречие или отсутствие признаков фазы — отказ с причиной, без догадок."""
    with pytest.raises(UnmappableEventError) as exc:
        map_envelope(envelope("event_medical_pre.json", **changes))
    assert exc.value.reason == reason


def test_technical_event_needs_title_three() -> None:
    """У техконтроля title_number, если он есть, должен быть 3."""
    with pytest.raises(UnmappableEventError) as exc:
        map_envelope(
            envelope(
                "event_technical.json", exam_datetime="2026-10-25T08:36:00+00:00", title_number=2
            )
        )
    assert exc.value.reason == "title_mismatch"


@pytest.mark.parametrize(
    "missing",
    ["blood_pressure_systolic", "blood_pressure_diastolic", "pulse", "temperature", "alcohol_ppm"],
)
def test_incomplete_vitals_are_rejected_with_field_names(missing: str) -> None:
    """Неполные медпоказатели (исторические рейсы): отказ, в причине названо поле."""
    raw = load("event_medical_pre.json")
    raw["payload"]["vitals"].pop(missing)
    with pytest.raises(UnmappableEventError) as exc:
        map_envelope(Envelope.model_validate(raw))
    assert exc.value.reason == "invalid_payload" and missing in (exc.value.detail or "")


def test_missing_approval_is_rejected() -> None:
    """Допуск (approved) обязателен."""
    with pytest.raises(UnmappableEventError):
        map_envelope(envelope("event_medical_pre.json", approved=None))


# ---------- справочники: реальные ответы ----------


def test_catalog_organization_sample() -> None:
    """Организация: name_full/name_short/legal_address/is_active."""
    org = OrganizationPayload.model_validate(load("catalog_organizations.json")[0])
    assert org.inn == "7700000001" and org.kpp == "770001001" and org.ogrn == "1027700000001"
    assert org.name == "ООО Тест Транс" and org.short_name == "ООО Тест Транс"
    assert org.legal_address == "г. Москва, ул. Тестовая, д. 1" and org.is_active is True
    assert org.updated_at == datetime(2026, 6, 4, 6, 29, 56, 962981, tzinfo=timezone.utc)
    assert org.work_format is None  # из Предрейса не приходит


def test_catalog_driver_sample() -> None:
    """Водитель: org_id, ФИО по частям, дата рождения «датой-временем», серия и номер прав."""
    driver = DriverPayload.model_validate(load("catalog_drivers.json")[0])
    assert driver.organization_id == uuid.UUID("1ebdb311-c1d4-46f1-b526-a475562bec9a")
    assert driver.full_name == "Водителев Василий Васильевич" and driver.gender is None
    assert driver.birth_date == date(1985, 5, 20)
    assert driver.license_number == "7700 7700123456"


def test_catalog_vehicle_sample() -> None:
    """ТС: plate_number, type."""
    vehicle = VehiclePayload.model_validate(load("catalog_vehicles.json")[0])
    assert (vehicle.plate, vehicle.brand, vehicle.model) == ("А123ВС77", "КАМАЗ", "65115")
    assert vehicle.vehicle_type == "грузовой"


def test_message_uuid_is_stable() -> None:
    """Идентификатор сообщения: сам UUID либо детерминированный из строки."""
    u = str(uuid.uuid4())
    assert message_uuid(u) == uuid.UUID(u)
    assert message_uuid("evt-1") == message_uuid("evt-1") != message_uuid("evt-2")


def test_pick_prefers_first_non_empty() -> None:
    """pick берёт первое непустое значение из вариантов путей."""
    data = {"a": {"b": ""}, "c": 5, "x.y": 7}
    assert pick(data, "a.b", "c") == 5
    assert pick(data, "x.y") == 7
    assert pick(data, "nope") is None

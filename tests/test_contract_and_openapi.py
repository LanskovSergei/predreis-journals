"""Контракт событий Предрейса (плоский формат ЭПЛ) и схема OpenAPI."""

from __future__ import annotations

import uuid
from datetime import timedelta, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from app.integrations.predreis.schemas import EplRecordEvent, IntegrationEvent, parse_tz_offset
from tests.factories import epl_event

ADAPTER: TypeAdapter[IntegrationEvent] = TypeAdapter(IntegrationEvent)


@pytest.mark.parametrize("event_type", ["T2", "T3", "T6"])
def test_valid_epl_events(event_type: str) -> None:
    """Т2/Т6 и Т3 разбираются в EplRecordEvent."""
    ev = ADAPTER.validate_python(epl_event(event_type))
    assert isinstance(ev, EplRecordEvent)
    assert ev.driver_full_name == "Ефимов Андрей Константинович"


@pytest.mark.parametrize(
    ("event_type", "field"),
    [
        ("T2", "blood_pressure_systolic"),
        ("T6", "temperature"),
        ("T2", "alcohol_ppm"),
        ("T2", "approved"),
        ("T3", "odometer"),
        ("T3", "vehicle_plate"),
        ("T3", "vehicle_id"),
    ],
)
def test_required_fields_by_title(event_type: str, field: str) -> None:
    """Для каждого вида титула обязательны свои поля."""
    raw = epl_event(event_type)
    raw[field] = None
    with pytest.raises(ValidationError, match=field):
        ADAPTER.validate_python(raw)


@pytest.mark.parametrize(
    "field", ["org_inn", "driver_birth_date", "specialist_user_id", "gis_uid", "exam_datetime"]
)
def test_common_required_fields(field: str) -> None:
    """Общая часть события обязательна; specialist_user_id не может быть пустым."""
    raw = epl_event("T2")
    del raw[field]
    with pytest.raises(ValidationError):
        ADAPTER.validate_python(raw)


def test_record_only_after_qr() -> None:
    """Запись создаётся только при получении QR."""
    with pytest.raises(ValidationError, match="QR"):
        ADAPTER.validate_python(epl_event("T2", qr_issued=False))


def test_unknown_event_type_rejected() -> None:
    """Титулы кроме Т2/Т3/Т6 не принимаются."""
    for bad in ("T4", "T1", "epl.record"):
        with pytest.raises(ValidationError):
            ADAPTER.validate_python({**epl_event("T2"), "event_type": bad})


def test_gender_is_optional_until_predreis_provides_it() -> None:
    """Пока пол не передаётся, событие всё равно принимается."""
    raw = epl_event("T2")
    del raw["driver_gender"]
    assert ADAPTER.validate_python(raw).driver_gender is None  # type: ignore[union-attr]


def test_event_id_is_derived_deterministically_when_missing() -> None:
    """Без event_id он вычисляется из рейса и титула — повторная доставка даёт тот же id."""
    raw = epl_event("T2")
    del raw["event_id"]
    a, b = ADAPTER.validate_python(raw), ADAPTER.validate_python(raw)
    assert a.event_id == b.event_id  # type: ignore[union-attr]
    other = ADAPTER.validate_python({**raw, "event_type": "T6"})
    assert other.event_id != a.event_id  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("raw", "minutes"),
    [("+03:00", 180), ("+0300", 180), ("-05:30", -330), (120, 120)],
)
def test_tz_offset_formats(raw: str | int, minutes: int) -> None:
    """Смещение пояса принимается как «+03:00», «+0300» или число минут."""
    assert parse_tz_offset(raw) == timedelta(minutes=minutes)
    with pytest.raises(ValueError, match="exam_tz_offset"):
        parse_tz_offset("MSK")


def test_naive_exam_datetime_uses_offset() -> None:
    """Время без пояса дополняется exam_tz_offset."""
    ev = ADAPTER.validate_python(epl_event("T2"))
    assert isinstance(ev, EplRecordEvent)
    assert ev.performed_at.utcoffset() == timedelta(hours=3)
    aware = ADAPTER.validate_python(epl_event("T2", exam_datetime="2026-10-14T08:20:00+00:00"))
    assert aware.performed_at.tzinfo == timezone.utc  # type: ignore[union-attr]


def test_unknown_fields_are_ignored() -> None:
    """Лишние поля Предрейса не ломают приём (расширение контракта без релиза журналов)."""
    ev = ADAPTER.validate_python({**epl_event("T2"), "new_field": "x"})
    assert ev.event_id  # type: ignore[union-attr]
    assert isinstance(ev.event_id, uuid.UUID)  # type: ignore[union-attr]


def test_openapi_builds_and_has_core_paths() -> None:
    """OpenAPI строится; ключевые пути для фронтенда на месте."""
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    for p in (
        "/api/v1/medical/records",
        "/api/v1/technical/records",
        "/api/v1/medical/records/sign",
        "/api/v1/exports/medical",
        "/api/v1/ejournals",
        "/integration/v1/events",
        "/health",
    ):
        assert p in paths

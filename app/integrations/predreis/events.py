"""Сообщения очереди RabbitMQ Предрейса → нормализованное ЭПЛ-событие.

Конверт известен из документации Предрейса: {id, event_type, entity_id, created_at, payload}.
Имена полей внутри payload сверяются по реальным сообщениям: что не удалось сопоставить,
попадает в таблицу `inbox_failures` вместе с исходным телом, а очередь не блокируется.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.integrations.predreis.schemas import EplRecordEvent, normalize_gender

EventType = Literal["journal.medical_exam", "journal.technical_exam"]
_MISSING = object()


class Envelope(BaseModel):
    """Конверт сообщения очереди."""

    id: str
    event_type: EventType
    entity_id: str | None = None
    created_at: datetime | None = None
    payload: dict[str, Any]


class UnmappableEventError(Exception):
    """Сообщение нельзя превратить в запись: причина (код) и подробности для оператора."""

    def __init__(self, reason: str, detail: str | None = None) -> None:
        """Сохраняет код причины и описание."""
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def message_uuid(message_id: str) -> uuid.UUID:
    """Идентификатор сообщения как UUID: сам id, если он UUID, иначе детерминированный uuid5."""
    try:
        return uuid.UUID(message_id)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"predreis/journal-event/{message_id}")


def _dig(data: dict[str, Any], path: str) -> Any:
    """Значение по пути «a.b.c» (в плоском словаре — по полному ключу)."""
    if path in data:
        return data[path]
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def pick(data: dict[str, Any], *paths: str) -> Any:
    """Первое непустое значение из перечисленных вариантов путей (None, если нет)."""
    for path in paths:
        value = _dig(data, path)
        if value is not _MISSING and value not in (None, ""):
            return value
    return None


def _group(p: dict[str, Any], group: str, name: str) -> Any:
    """Поле из вложенного блока (`vitals`, `checks`) либо с верхнего уровня."""
    return pick(p, f"{group}.{name}", name, f"inspection.{name}")


def _license(p: dict[str, Any]) -> str | None:
    """Права одной строкой: «серия номер»; нет серии — номер как есть (серия может быть внутри)."""
    series = pick(p, "driver.license_series", "driver_license_series")
    number = pick(
        p, "driver.license_number", "driver.license", "driver_license_number", "driver_license"
    )
    if series and number:
        return f"{series} {number}"
    return str(number) if number else None


def _split_name(full: str | None) -> tuple[str | None, str | None, str | None]:
    """Делит «Фамилия Имя Отчество» на три части (отчество может отсутствовать)."""
    parts = (full or "").split(None, 2)
    parts += [None] * (3 - len(parts))  # type: ignore[list-item]
    return parts[0], parts[1], parts[2]


def _names(p: dict[str, Any], prefix: str) -> tuple[str | None, str | None, str | None]:
    """ФИО из раздельных полей или из одного поля full_name."""
    last = pick(p, f"{prefix}.last_name", f"{prefix}_last_name")
    first = pick(p, f"{prefix}.first_name", f"{prefix}_first_name")
    middle = pick(p, f"{prefix}.middle_name", f"{prefix}_middle_name")
    if last and first:
        return last, first, middle
    return _split_name(pick(p, f"{prefix}.full_name", f"{prefix}.name", f"{prefix}_full_name"))


def _phase_title(p: dict[str, Any]) -> str | None:
    """Т2 (предрейсовый) или Т6 (послерейсовый) по `title_number` и `exam_type`.

    Если оба признака есть и противоречат друг другу, это ошибка данных, а не повод угадывать.
    """
    by_title: str | None = None
    raw = pick(p, "title_number", "title")
    if raw is not None:
        digits = str(raw).upper().lstrip("T")
        if digits not in {"2", "6"}:
            raise UnmappableEventError("title_mismatch", f"title_number={raw!r} не медосмотр")
        by_title = f"T{digits}"
    by_type: str | None = None
    kind = str(pick(p, "exam_type", "phase") or "").strip().lower()
    if kind in {"pre_trip", "pre"}:
        by_type = "T2"
    elif kind in {"post_trip", "post"}:
        by_type = "T6"
    elif kind:
        raise UnmappableEventError("exam_type_unknown", f"exam_type={kind!r}")
    if by_title and by_type and by_title != by_type:
        raise UnmappableEventError("title_conflict", f"title_number={raw!r}, exam_type={kind!r}")
    if by_title or by_type:
        return by_title or by_type
    if pick(p, "is_post_trip", "medical.is_post_trip") is True:
        return "T6"
    if pick(p, "is_pre_trip", "medical.is_pre_trip") is True:
        return "T2"
    return None


def map_envelope(env: Envelope) -> EplRecordEvent:
    """Строит нормализованное событие; бросает UnmappableEventError с причиной."""
    p = env.payload
    technical = env.event_type == "journal.technical_exam"
    title: str | None
    if technical:
        raw_title = pick(p, "title_number", "title")
        if raw_title is not None and str(raw_title).upper().lstrip("T") != "3":
            raise UnmappableEventError(
                "title_mismatch", f"title_number={raw_title!r} не техконтроль"
            )
        title = "T3"
    else:
        title = _phase_title(p)
        if title is None:
            raise UnmappableEventError(
                "phase_unknown", "не определён предрейсовый/послерейсовый осмотр"
            )

    d_last, d_first, d_mid = _names(p, "driver")
    s_last, s_first, s_mid = _names(p, "specialist")
    data: dict[str, Any] = {
        "event_type": title,
        "event_id": message_uuid(env.id),
        "waybill_id": pick(p, "waybill_id", "waybill.id", "trip_id") or env.entity_id,
        "waybill_number": pick(p, "waybill_number", "waybill.number"),
        "gis_uid": pick(p, "gis_uid", "gis_epd_uid", "gis.uid", "uid_gis"),
        "edweb_document_id": pick(
            p, "title_doc_id", "edweb_document_id", "edweb_id", "document_id"
        ),
        "organization_id": pick(p, "organization.id", "organization_id", "org_id"),
        "org_inn": pick(p, "organization.inn", "org_inn", "inn"),
        "org_kpp": pick(p, "organization.kpp", "org_kpp"),
        "org_ogrn": pick(p, "organization.ogrn", "org_ogrn"),
        "org_name": pick(
            p, "organization.name_full", "organization.name", "organization.full_name", "org_name"
        ),
        "org_short_name": pick(
            p, "organization.name_short", "organization.short_name", "org_short_name"
        ),
        "org_address": pick(
            p, "organization.legal_address", "organization.address", "org_address"
        ),
        "driver_id": pick(p, "driver.id", "driver_id"),
        "driver_last_name": d_last,
        "driver_first_name": d_first,
        "driver_middle_name": d_mid,
        "driver_birth_date": pick(p, "driver.birth_date", "driver_birth_date"),
        "driver_gender": normalize_gender(pick(p, "driver.gender", "driver_gender")),
        "driver_license": _license(p),
        "vehicle_id": pick(p, "vehicle.id", "vehicle_id"),
        "specialist_user_id": pick(p, "specialist.id", "specialist.user_id", "specialist_user_id"),
        "specialist_last_name": s_last,
        "specialist_first_name": s_first,
        "specialist_middle_name": s_mid,
        "exam_datetime": pick(
            p, "exam_datetime", "exam_at", "examined_at", "inspection.exam_datetime"
        ),
        "exam_tz_offset": pick(p, "exam_tz_offset", "tz_offset"),
        "signature_serial": pick(p, "signature.serial", "signature_serial"),
        "signature_owner": pick(p, "signature.owner", "signature_owner"),
        "signature_valid_from": pick(p, "signature.valid_from", "signature_valid_from"),
        "signature_valid_to": pick(p, "signature.valid_to", "signature_valid_to"),
        "notes": pick(p, "notes", "note", "inspection.notes"),
        "recorded_at": pick(p, "recorded_at", "inspection.recorded_at"),
        "approved": pick(p, "approved", "admitted", "допуск", "inspection.approved"),
        "critical_flag": pick(p, "critical_flag"),
    }
    if technical:
        data |= {
            "vehicle_plate": pick(
                p, "vehicle.plate_number", "vehicle.plate", "vehicle.gos_number", "vehicle_plate"
            ),
            "vehicle_brand": pick(p, "vehicle.brand", "vehicle_brand"),
            "vehicle_model": pick(p, "vehicle.model", "vehicle_model"),
            "vehicle_type": pick(p, "vehicle.type", "vehicle_type"),
            "vehicle_category": pick(p, "vehicle.category", "vehicle_category"),
            "odometer": pick(p, "odometer", "odometer_value", "inspection.odometer"),
            "brakes_ok": _group(p, "checks", "brakes_ok"),
            "lighting_ok": _group(p, "checks", "lighting_ok"),
            "tires_ok": _group(p, "checks", "tires_ok"),
            "released": pick(p, "released"),
            "mechanic_position": pick(p, "mechanic_position"),
        }
    else:
        data |= {
            "blood_pressure_systolic": _group(p, "vitals", "blood_pressure_systolic"),
            "blood_pressure_diastolic": _group(p, "vitals", "blood_pressure_diastolic"),
            "pulse": _group(p, "vitals", "pulse"),
            "temperature": _group(p, "vitals", "temperature"),
            "alcohol_detected": _group(p, "vitals", "alcohol_detected"),
            "alcohol_ppm": _group(p, "vitals", "alcohol_ppm"),
            "complaints": pick(p, "complaints", "inspection.complaints"),
            "harmful_factors_detected": pick(
                p, "harmful_factors_detected", "inspection.harmful_factors_detected"
            ),
            "harmful_factors": pick(p, "harmful_factors", "inspection.harmful_factors"),
            "medic_license_series": pick(p, "medic_license_series"),
            "medic_license_number": pick(p, "medic_license_number"),
            "medic_license_issued": pick(p, "medic_license_issued"),
            "medic_license_expires": pick(p, "medic_license_expires"),
            "medic_org_name": pick(p, "medic_org_name"),
            "vid_mo": pick(p, "vid_mo"),
            "is_pre_trip": pick(p, "is_pre_trip"),
            "is_post_trip": pick(p, "is_post_trip"),
        }
    if data.get("exam_datetime") is None:
        raise UnmappableEventError(
            "exam_time_missing", "в событии нет времени осмотра (старый осмотр без времени)"
        )
    try:
        return EplRecordEvent.model_validate({k: v for k, v in data.items() if v is not None})
    except ValidationError as exc:
        problems = sorted(
            {
                ".".join(str(x) for x in e["loc"]) or str(e["msg"]).removeprefix("Value error, ")
                for e in exc.errors()
            }
        )
        raise UnmappableEventError("invalid_payload", "; ".join(problems)) from exc

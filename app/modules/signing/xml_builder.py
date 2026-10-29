"""Машиночитаемое представление записи (XML) по схеме xmlschemas/record.xsd."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from lxml import etree

from app.domain.enums import JournalKind, RecordSource
from app.models.records import AnyRecord, MedicalRecord, TechnicalRecord
from app.xmlschemas import FORMAT_VERSION, NS_RECORD, ensure_valid

_NSMAP = {None: NS_RECORD}


def _sub(parent: etree._Element, tag: str, value: object | None) -> etree._Element:
    """Добавляет дочерний элемент в пространстве имён записи."""
    el = etree.SubElement(parent, f"{{{NS_RECORD}}}{tag}")
    el.text = "" if value is None else str(value)
    return el


def _sub_opt(parent: etree._Element, tag: str, value: object | None) -> None:
    """Добавляет элемент, только если значение задано."""
    if value is not None and str(value).strip() != "":
        _sub(parent, tag, value)


def _decimal(value: Decimal) -> str:
    """Десятичное число без экспоненты и лишних нулей справа от разделителя."""
    return format(value, "f")


def _driver(parent: etree._Element, driver: dict[str, Any]) -> None:
    """Блок «Водитель» из снимка реквизитов."""
    el = etree.SubElement(parent, f"{{{NS_RECORD}}}Driver")
    _sub(el, "FullName", driver.get("full_name"))
    _sub_opt(
        el, "BirthDate", driver.get("birth_date")
    )  # у водителя дата рождения может быть не указана
    _sub_opt(el, "Gender", driver.get("gender"))


def build_record_xml(kind: JournalKind, record: AnyRecord) -> bytes:
    """Строит XML электронной записи и проверяет его по XSD (ошибка — XmlInvalidError)."""
    snap = record.snapshot
    root = etree.Element(
        f"{{{NS_RECORD}}}ElectronicRecord",
        {"version": FORMAT_VERSION, "id": str(record.id)},
        nsmap=_NSMAP,
    )
    _sub(root, "Source", record.source.value)
    if record.source is RecordSource.EPL:
        waybill = etree.SubElement(root, f"{{{NS_RECORD}}}Waybill")
        _sub(waybill, "Number", record.waybill_number)
        _sub(waybill, "GisUid", record.gis_uid)
        _sub(waybill, "Title", f"T{record.epl_title_number}")

    org = snap.get("organization", {})
    org_el = etree.SubElement(root, f"{{{NS_RECORD}}}Organization")
    _sub(org_el, "INN", org.get("inn"))
    _sub_opt(org_el, "KPP", org.get("kpp"))
    _sub_opt(org_el, "OGRN", org.get("ogrn"))
    _sub(org_el, "Name", org.get("name"))
    _sub_opt(org_el, "ShortName", org.get("short_name"))
    _sub_opt(org_el, "LegalAddress", org.get("legal_address"))

    _sub(root, "PerformedAt", record.performed_at.isoformat())
    specialist = etree.SubElement(
        root, f"{{{NS_RECORD}}}Specialist", {"userId": str(record.specialist_user_id)}
    )
    _sub(specialist, "FullName", snap.get("specialist", {}).get("full_name"))

    if isinstance(record, MedicalRecord):
        exam = etree.SubElement(root, f"{{{NS_RECORD}}}MedicalExamination")
        _sub(exam, "Phase", record.phase.value)
        _driver(exam, snap.get("driver", {}))
        _sub(exam, "Complaints", record.complaints)
        pressure = etree.SubElement(exam, f"{{{NS_RECORD}}}BloodPressure")
        _sub(pressure, "Systolic", record.bp_systolic)
        _sub(pressure, "Diastolic", record.bp_diastolic)
        _sub(exam, "Pulse", record.pulse)
        _sub(exam, "Temperature", _decimal(record.temperature))
        _sub(exam, "Alcohol", _decimal(record.alcohol_mgl))
        if record.harmful_factors is not None:
            _sub(exam, "HarmfulFactors", record.harmful_factors.value)
        _sub_opt(exam, "HarmfulFactorsNote", record.harmful_factors_note)
        _sub(exam, "Result", record.result.value)
    else:
        if not (
            isinstance(record, TechnicalRecord)
        ):  # явная проверка: assert исчезает при python -O
            raise RuntimeError("Нарушено внутреннее условие")
        inspection = etree.SubElement(root, f"{{{NS_RECORD}}}TechnicalInspection")
        vehicle = snap.get("vehicle", {})
        veh = etree.SubElement(inspection, f"{{{NS_RECORD}}}Vehicle")
        _sub(veh, "Brand", vehicle.get("brand"))
        _sub(veh, "Model", vehicle.get("model"))
        _sub_opt(veh, "Type", vehicle.get("vehicle_type"))
        _sub(veh, "Plate", vehicle.get("plate"))
        if snap.get("driver"):
            _driver(inspection, snap["driver"])
        _sub(inspection, "Odometer", record.odometer)
        _sub(inspection, "Result", record.result.value)

    _sub_opt(root, "Note", record.note)
    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    ensure_valid(data, "record", code="record_xml_invalid")
    return data

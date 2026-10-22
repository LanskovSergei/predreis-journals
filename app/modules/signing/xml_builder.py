"""Машиночитаемое представление записи (XML). Схема — черновик, XSD утверждается отдельно."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from app.domain.enums import JournalKind
from app.models.records import MedicalRecord, TechnicalRecord

SCHEMA_VERSION = "1.0"


def _sub(parent: ET.Element, tag: str, value: object | None) -> ET.Element:
    """Добавляет дочерний элемент с текстовым значением (None → пустой элемент)."""
    el = ET.SubElement(parent, tag)
    el.text = "" if value is None else str(value)
    return el


def build_record_xml(kind: JournalKind, record: MedicalRecord | TechnicalRecord) -> bytes:
    """Строит XML электронной записи (детерминированный порядок элементов)."""
    root = ET.Element(
        "ElectronicRecord",
        {"version": SCHEMA_VERSION, "kind": kind.value, "id": str(record.id)},
    )
    org = record.snapshot.get("organization", {})
    org_el = ET.SubElement(root, "Organization")
    _sub(org_el, "INN", org.get("inn"))
    _sub(org_el, "Name", org.get("name"))
    _sub(root, "PerformedAt", record.performed_at.isoformat())
    specialist = ET.SubElement(root, "Specialist", {"userId": str(record.specialist_user_id)})
    _sub(specialist, "FullName", record.snapshot.get("specialist", {}).get("full_name"))
    driver = record.snapshot.get("driver")

    if isinstance(record, MedicalRecord):
        _sub(root, "Phase", record.phase.value)
        drv = ET.SubElement(root, "Driver")
        _sub(drv, "FullName", (driver or {}).get("full_name"))
        _sub(drv, "BirthDate", (driver or {}).get("birth_date"))
        _sub(drv, "Gender", (driver or {}).get("gender"))
        vitals = ET.SubElement(root, "Examination")
        _sub(vitals, "Complaints", record.complaints)
        _sub(vitals, "BloodPressure", f"{record.bp_systolic}/{record.bp_diastolic}")
        _sub(vitals, "Pulse", record.pulse)
        _sub(vitals, "Temperature", record.temperature)
        _sub(vitals, "AlcoholMgL", record.alcohol_mgl)
        _sub(vitals, "HarmfulFactors", record.harmful_factors.value)
        _sub(vitals, "HarmfulFactorsNote", record.harmful_factors_note)
    else:
        assert isinstance(record, TechnicalRecord)
        vehicle = record.snapshot.get("vehicle", {})
        veh = ET.SubElement(root, "Vehicle")
        _sub(veh, "Brand", vehicle.get("brand"))
        _sub(veh, "Model", vehicle.get("model"))
        _sub(veh, "Type", vehicle.get("vehicle_type"))
        _sub(veh, "Plate", vehicle.get("plate"))
        _sub(root, "Odometer", record.odometer)
        if driver:
            drv = ET.SubElement(root, "Driver")
            _sub(drv, "FullName", driver.get("full_name"))

    _sub(root, "Result", record.result.value)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)

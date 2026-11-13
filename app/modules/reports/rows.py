"""Подготовка строк отчётов: форматирование и скрытие сведений, составляющих врачебную тайну."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.core.timeutils import to_local
from app.domain.enums import HarmfulFactors, InspectionPhase, InspectionResult
from app.domain.masking import redact_medical
from app.models.documents import RecordDocument
from app.models.records import MedicalRecord, TechnicalRecord

GENDER_LABEL = {"M": "М", "F": "Ж"}


def fmt_date(value: datetime) -> str:
    """Дата в формате ДД.ММ.ГГГГ (местное время)."""
    return to_local(value).strftime("%d.%m.%Y")


def fmt_time(value: datetime) -> str:
    """Время в формате ЧЧ:ММ (местное время)."""
    return to_local(value).strftime("%H:%M")


def fmt_decimal(value: Decimal) -> str:
    """Число с десятичной запятой."""
    return str(value).replace(".", ",")


def signature_view(
    doc: RecordDocument | None, specialist_name: str | None = None
) -> dict[str, str] | None:
    """Данные подписи для ячейки таблицы (сертификат или хотя бы ФИО специалиста)."""
    owner = (doc.cert_subject if doc else None) or specialist_name or ""
    serial = (doc.cert_serial if doc else None) or ""
    if not serial and not owner:
        return None
    return {
        "serial": serial or "—",
        "owner": owner,
        "valid_from": fmt_date(doc.cert_valid_from) if doc and doc.cert_valid_from else "",
        "valid_to": fmt_date(doc.cert_valid_to) if doc and doc.cert_valid_to else "",
    }


def medical_row(n: int, rec: MedicalRecord, doc: RecordDocument | None) -> dict[str, Any]:
    """Строка отчёта по медосмотрам; медицинские показатели заменяются на N/A (323-ФЗ)."""
    driver = rec.snapshot.get("driver", {})
    birth = driver.get("birth_date", "")
    if birth:
        y, m, d = birth.split("-")
        birth = f"{d}.{m}.{y}"
    pre = "предрейсовый" if rec.phase is InspectionPhase.PRE else "послерейсовый"
    row: dict[str, Any] = {
        "n": n,
        "date": fmt_date(rec.performed_at),
        "time": fmt_time(rec.performed_at),
        "driver_name": driver.get("full_name", ""),
        "birth_date": birth,
        "gender": GENDER_LABEL.get(driver.get("gender", ""), ""),
        "complaints": rec.complaints,
        "blood_pressure": f"{rec.bp_systolic}/{rec.bp_diastolic}",
        "pulse": rec.pulse,
        "temperature": fmt_decimal(rec.temperature),
        "alcohol_permille": fmt_decimal(rec.alcohol_permille),
        "harmful_factors": {
            HarmfulFactors.ABSENT: "отсутствуют",
            HarmfulFactors.DETECTED: "выявлены",
            None: "не определялись",
        }[rec.harmful_factors],
        "conclusion": "допущен" if rec.result is InspectionResult.ADMITTED else "не допущен",
        "phase": pre,
        "signature": signature_view(doc, rec.snapshot.get("specialist", {}).get("full_name")),
    }
    return redact_medical(row)


def technical_row(n: int, rec: TechnicalRecord, doc: RecordDocument | None) -> dict[str, Any]:
    """Строка отчёта по техконтролю."""
    vehicle = rec.snapshot.get("vehicle", {})
    return {
        "n": n,
        "date": fmt_date(rec.performed_at),
        "time": fmt_time(rec.performed_at),
        "vehicle_name": f"{vehicle.get('brand', '')} {vehicle.get('model', '')}".strip(),
        "plate": vehicle.get("plate", ""),
        "odometer": rec.odometer,
        "conclusion": "пройден" if rec.result is InspectionResult.ADMITTED else "не пройден",
        "specialist_name": rec.snapshot.get("specialist", {}).get("full_name", ""),
        "signature": signature_view(doc, rec.snapshot.get("specialist", {}).get("full_name")),
    }

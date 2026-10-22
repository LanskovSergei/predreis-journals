"""Врачебная тайна и отчётные PDF."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain.enums import (
    HarmfulFactors,
    InspectionPhase,
    InspectionResult,
    JournalKind,
    RecordSource,
    RecordStatus,
)
from app.domain.masking import NOT_AVAILABLE, redact_medical
from app.models.documents import RecordDocument
from app.models.records import MedicalRecord, TechnicalRecord
from app.modules.reports.render import render_html
from app.modules.reports.rows import medical_row, technical_row
from app.modules.reports.service import render_single_record_pdf

MSK = timezone(timedelta(hours=3))
SNAP = {
    "organization": {
        "inn": "7707083893",
        "name": "ООО «Тест»",
        "short_name": "Тест",
        "legal_address": "Москва",
    },
    "driver": {
        "full_name": "Ефимов Андрей Константинович",
        "birth_date": "1974-07-21",
        "gender": "M",
    },
    "vehicle": {"brand": "Грузовой ГАЗон", "model": "2824ЕИ", "plate": "О224ЕК790"},
    "specialist": {"full_name": "Абдуллаева Гульзана Абутдиновна"},
}


def _medical() -> MedicalRecord:
    """Несохранённая запись медосмотра с характерными значениями."""
    return MedicalRecord(
        id=uuid.uuid4(),
        status=RecordStatus.SIGNED,
        source=RecordSource.MANUAL,
        phase=InspectionPhase.PRE,
        performed_at=datetime(2026, 10, 14, 8, 20, tzinfo=MSK),
        snapshot=SNAP,
        complaints="жалоб-нет-секрет",
        bp_systolic=137,
        bp_diastolic=84,
        pulse=72,
        temperature=Decimal("36.6"),
        alcohol_mgl=Decimal("0.00"),
        harmful_factors=HarmfulFactors.ABSENT,
        result=InspectionResult.ADMITTED,
        specialist_user_id=uuid.uuid4(),
    )


def _doc(record_id: uuid.UUID, kind: JournalKind) -> RecordDocument:
    """Электронный документ с данными сертификата."""
    return RecordDocument(
        record_kind=kind,
        record_id=record_id,
        cert_serial="f18dd73747eccc4ab0d2b1ee00d4040e",
        cert_subject="Абдуллаева Гульзана Абутдиновна",
        cert_valid_from=datetime(2024, 9, 17, tzinfo=MSK),
        cert_valid_to=datetime(2039, 6, 19, tzinfo=MSK),
    )


def test_redact_medical_hides_only_secret_fields() -> None:
    """Скрываются показатели здоровья, ФИО и заключение остаются."""
    row = redact_medical(
        {"driver_name": "Иванов", "pulse": 72, "complaints": "x", "conclusion": "допущен"}
    )
    assert row["pulse"] == row["complaints"] == NOT_AVAILABLE
    assert row["driver_name"] == "Иванов"
    assert row["conclusion"] == "допущен"


def test_medical_row_never_contains_vitals() -> None:
    """В строке отчёта нет ни одного медицинского показателя."""
    rec = _medical()
    row = medical_row(1, rec, _doc(rec.id, JournalKind.MEDICAL))
    flat = " ".join(str(v) for v in row.values())
    for secret in ("137/84", "36,6", "жалоб-нет-секрет", "72"):
        assert secret not in flat
    assert row["date"] == "14.10.2026"
    assert row["time"] == "08:20"
    assert row["conclusion"] == "допущен"


def test_html_has_privacy_notice_and_no_signature_stamp() -> None:
    """В выгрузке — дисклеймер 323-ФЗ и нет плашек, имитирующих ЭЦП (ТЗ, стр. 19)."""
    rec = _medical()
    html = render_html(
        "medical_report.html",
        title="Отчёт",
        rows=[medical_row(1, rec, _doc(rec.id, JournalKind.MEDICAL))],
        customer={"name": "Тест", "inn": "7707083893", "address": "Москва"},
        executor={
            "name": "ООО «ПРЕДРЕЙС»",
            "inn": "5027236147",
            "address": "-",
            "phone": "-",
            "email": "-",
        },
        executor_license="№ Л041",
        privacy_notice="323-ФЗ",
        period_from="01.10.2026",
        period_to="14.10.2026",
        stamp=None,
    )
    assert "323-ФЗ" in html
    assert "N/A" in html
    assert "Файл подписан" not in html
    assert "page-break-inside: avoid" in html


@pytest.mark.parametrize("kind", [JournalKind.MEDICAL, JournalKind.TECHNICAL])
async def test_single_record_pdf_is_generated(kind: JournalKind) -> None:
    """PDF электронной записи формируется WeasyPrint без ошибок."""
    if kind is JournalKind.MEDICAL:
        rec: MedicalRecord | TechnicalRecord = _medical()
    else:
        rec = TechnicalRecord(
            id=uuid.uuid4(),
            status=RecordStatus.SIGNED,
            source=RecordSource.MANUAL,
            performed_at=datetime(2026, 10, 14, 8, 36, tzinfo=MSK),
            snapshot=SNAP,
            odometer=1167,
            result=InspectionResult.ADMITTED,
            specialist_user_id=uuid.uuid4(),
        )
        assert technical_row(1, rec, None)["conclusion"] == "пройден"
    pdf = await render_single_record_pdf(kind, rec, _doc(rec.id, kind))
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000

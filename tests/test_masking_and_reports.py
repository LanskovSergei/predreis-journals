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
from app.modules.reports.rows import medical_row, technical_row
from app.modules.reports.service import render_registry_pdf, render_single_record_pdf

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


def _text(pdf: bytes) -> str:
    """Весь текст PDF (для проверок содержимого)."""
    from io import BytesIO

    from pypdf import PdfReader

    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)


async def test_registry_pdf_hides_medical_data_and_has_privacy_notice() -> None:
    """В выгрузке — дисклеймер 323-ФЗ, показатели скрыты (N/A), ФИО и заключение на месте."""
    rec = _medical()
    pdf = await render_registry_pdf(
        kind=JournalKind.MEDICAL,
        customer={"name": "Тест", "inn": "7707083893", "address": "Москва"},
        records=[rec],
        docs={rec.id: _doc(rec.id, JournalKind.MEDICAL)},
        period_from="01.10.2026",
        period_to="31.10.2026",
    )
    text = _text(pdf)
    assert pdf.startswith(b"%PDF")
    for visible in ("323-ФЗ", "N/A", "Ефимов", "допущен", "14.10.2026", "08:20", "стр. 1 из 1"):
        assert visible in text, visible
    for secret in ("137/84", "36,6", "жалоб-нет-секрет"):
        assert secret not in text, secret
    assert "Файл подписан" not in text  # без плашки, пока журнал не подписан


async def test_signed_registry_pdf_has_stamp_on_last_page() -> None:
    """Подписанный журнал: плашка с данными сертификата на последней странице."""
    recs = [_medical() for _ in range(40)]
    for r in recs:
        r.id = uuid.uuid4()
    stamp = {
        "serial": "0f18dd73747eccc4ab0d2b1ee00d4040",
        "subject": "ООО «ПРЕДРЕЙС»",
        "valid_from": "17.09.2024",
        "valid_to": "19.06.2039",
    }
    pdf = await render_registry_pdf(
        kind=JournalKind.MEDICAL,
        customer={"name": "Тест", "inn": "7707083893", "address": None},
        records=recs,
        docs={r.id: _doc(r.id, JournalKind.MEDICAL) for r in recs},
        period_from="01.10.2026",
        period_to="31.10.2026",
        stamp=stamp,
    )
    from io import BytesIO

    from pypdf import PdfReader

    pages = PdfReader(BytesIO(pdf)).pages
    assert len(pages) > 1
    last = pages[-1].extract_text()
    assert "Файл подписан электронной цифровой подписью" in last and stamp["serial"] in last
    assert "Файл подписан" not in pages[0].extract_text()
    assert f"стр. {len(pages)} из {len(pages)}" in last
    # Шапка таблицы повторяется на каждой странице.
    assert all("Ф.И.О. водителя" in p.extract_text() for p in pages[:-1])


async def test_long_words_and_empty_values_do_not_break_layout() -> None:
    """Очень длинные слова режутся, пустые значения (нет адреса ИП, нет подписи) не мешают."""
    rec = _medical()
    snap = {**SNAP, "driver": {**SNAP["driver"], "full_name": "Ы" * 120}}
    rec.snapshot = snap
    pdf = await render_registry_pdf(
        kind=JournalKind.MEDICAL,
        customer={"name": "ИП " + "Я" * 90, "inn": "770000000000", "address": None},
        records=[rec],
        docs={},
        period_from="01.10.2026",
        period_to="31.10.2026",
    )
    assert pdf.startswith(b"%PDF") and "—" in _text(pdf)


@pytest.mark.parametrize("kind", [JournalKind.MEDICAL, JournalKind.TECHNICAL])
async def test_single_record_pdf_is_generated(kind: JournalKind) -> None:
    """PDF электронной записи формируется без ошибок."""
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

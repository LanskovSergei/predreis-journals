"""Детерминированные образцы записей и документов для тестов схем и для docs/examples."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.domain.enums import (
    HarmfulFactors,
    InspectionPhase,
    InspectionResult,
    JournalKind,
    RecordSource,
    RecordStatus,
)
from app.models.records import MedicalRecord, TechnicalRecord
from app.modules.ejournal.xml_builder import (
    FileRef,
    JournalRecordRef,
    ManifestFile,
    Party,
    SignatureRef,
    build_journal_xml,
    build_manifest_xml,
)
from app.modules.signing.xml_builder import build_record_xml

MSK = timezone(timedelta(hours=3))
U = uuid.UUID
SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64

SNAPSHOT = {
    "organization": {
        "inn": "7707083893",
        "kpp": "770701001",
        "ogrn": "1027700132195",
        "name": "ООО «Тестовая логистика»",
        "short_name": "Тест-Логистик",
        "legal_address": "г. Москва, ул. Тестовая, 1",
    },
    "driver": {
        "full_name": "Ефимов Андрей Константинович",
        "birth_date": "1974-07-21",
        "gender": "M",
    },
    "vehicle": {
        "brand": "Грузовой ГАЗон",
        "model": "2824ЕИ",
        "vehicle_type": "грузовой",
        "plate": "О224ЕК790",
    },
    "specialist": {"full_name": "Абдуллаева Гульзана Абутдиновна"},
}


def medical(source: RecordSource = RecordSource.MANUAL, **over: object) -> MedicalRecord:
    """Запись медосмотра (несохранённая)."""
    values: dict[str, object] = {
        "id": U("11111111-1111-4111-8111-111111111111"),
        "status": RecordStatus.UNSIGNED,
        "source": source,
        "phase": InspectionPhase.PRE,
        "performed_at": datetime(2026, 10, 14, 8, 20, tzinfo=MSK),
        "snapshot": SNAPSHOT,
        "complaints": "отсутствуют",
        "bp_systolic": 137,
        "bp_diastolic": 84,
        "pulse": 72,
        "temperature": Decimal("36.6"),
        "alcohol_mgl": Decimal("0.00"),
        "harmful_factors": HarmfulFactors.ABSENT,
        "result": InspectionResult.ADMITTED,
        "specialist_user_id": U("22222222-2222-4222-8222-222222222222"),
    }
    if source is RecordSource.EPL:
        values |= {
            "status": RecordStatus.SIGNED,
            "epl_waybill_id": U("33333333-3333-4333-8333-333333333333"),
            "epl_title_number": 2,
            "waybill_number": "ЭПЛ-2026-000123",
            "gis_uid": "7f1c1f0a-0000-4000-8000-000000000001",
            "note": "Проверено повторно",
        }
    return MedicalRecord(**{**values, **over})


def technical(**over: object) -> TechnicalRecord:
    """Запись техконтроля (несохранённая)."""
    values: dict[str, object] = {
        "id": U("44444444-4444-4444-8444-444444444444"),
        "status": RecordStatus.UNSIGNED,
        "source": RecordSource.MANUAL,
        "performed_at": datetime(2026, 10, 14, 8, 36, tzinfo=MSK),
        "snapshot": SNAPSHOT,
        "odometer": 1167,
        "result": InspectionResult.ADMITTED,
        "specialist_user_id": U("55555555-5555-4555-8555-555555555555"),
    }
    return TechnicalRecord(**{**values, **over})


def journal_xml() -> bytes:
    """Образец journal.xml с двумя записями (одна — со всеми файлами)."""
    full = JournalRecordRef(
        record_id=U("11111111-1111-4111-8111-111111111111"),
        source=RecordSource.MANUAL,
        performed_at=datetime(2026, 10, 14, 8, 20, tzinfo=MSK),
        result=InspectionResult.ADMITTED,
        xml=FileRef("records/11111111-1111-4111-8111-111111111111/record.xml", SHA_A),
        pdf=FileRef("records/11111111-1111-4111-8111-111111111111/record.pdf", SHA_B),
        signature=SignatureRef(
            "records/11111111-1111-4111-8111-111111111111/record.xml.sig",
            SHA_C,
            "f18dd73747eccc4ab0d2b1ee00d4040e",
            "Абдуллаева Гульзана Абутдиновна",
        ),
        timestamp=FileRef("records/11111111-1111-4111-8111-111111111111/record.xml.tsp", SHA_A),
    )
    epl = JournalRecordRef(
        record_id=U("66666666-6666-4666-8666-666666666666"),
        source=RecordSource.EPL,
        performed_at=datetime(2026, 10, 13, 17, 5, tzinfo=MSK),
        result=InspectionResult.NOT_ADMITTED,
        xml=FileRef("records/66666666-6666-4666-8666-666666666666/record.xml", SHA_B),
    )
    return build_journal_xml(
        journal_id=U("77777777-7777-4777-8777-777777777777"),
        kind=JournalKind.MEDICAL,
        issuer=Party("5027236147", "ООО «ПРЕДРЕЙС»"),
        organization=Party("7707083893", "ООО «Тестовая логистика»"),
        period_from=date(2026, 10, 1),
        period_to=date(2026, 10, 31),
        created_at=datetime(2026, 11, 1, 9, 0, tzinfo=MSK),
        records=[full, epl],
    )


def manifest_xml() -> bytes:
    """Образец manifest.xml."""
    rid = U("11111111-1111-4111-8111-111111111111")
    base = f"records/{rid}"
    return build_manifest_xml(
        container_id=U("77777777-7777-4777-8777-777777777777"),
        created_at=datetime(2026, 11, 1, 9, 0, tzinfo=MSK),
        generator="predreis-journals/0.1.0",
        files=[
            ManifestFile("journal.xml", "journal-xml", 2048, SHA_A),
            ManifestFile(
                "journal.xml.sig", "journal-signature", 512, SHA_B, signed_file="journal.xml"
            ),
            ManifestFile(f"{base}/record.xml", "record-xml", 1024, SHA_C, record_id=rid),
            ManifestFile(
                f"{base}/record.xml.sig",
                "record-signature",
                256,
                SHA_A,
                record_id=rid,
                signed_file=f"{base}/record.xml",
            ),
            ManifestFile("audit/audit-log.json", "audit-log", 4096, SHA_B),
            ManifestFile("README.txt", "readme", 900, SHA_C),
        ],
    )


def all_examples() -> dict[str, bytes]:
    """Все образцы: имя файла → содержимое."""
    return {
        "record-medical.xml": build_record_xml(JournalKind.MEDICAL, medical()),
        "record-medical-epl.xml": build_record_xml(
            JournalKind.MEDICAL,
            medical(RecordSource.EPL, id=U("66666666-6666-4666-8666-666666666666")),
        ),
        "record-technical.xml": build_record_xml(JournalKind.TECHNICAL, technical()),
        "journal.xml": journal_xml(),
        "manifest.xml": manifest_xml(),
    }

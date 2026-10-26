"""Исправление записей «Водителя+» с ошибочным «absent» (скрипт обслуживания)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import (
    HarmfulFactors,
    InspectionPhase,
    InspectionResult,
    RecordSource,
    RecordStatus,
)
from app.maintenance.repair_harmful_factors import repair
from app.models.audit import AuditLog
from app.models.integration import InboxEvent
from app.models.records import MedicalRecord
from tests.factories import seed

pytestmark = pytest.mark.asyncio
NOW = datetime(2026, 10, 14, 8, 20, tzinfo=timezone(timedelta(hours=3)))


async def _epl_record(
    session: AsyncSession, w, *, flag: bool | None, status: RecordStatus, title: int = 2
) -> uuid.UUID:
    """EPL-запись «absent» и сохранённое событие с указанным признаком (как при старой ошибке)."""
    waybill = uuid.uuid4()
    session.add(
        MedicalRecord(
            id=uuid.uuid4(),
            status=status,
            source=RecordSource.EPL,
            epl_waybill_id=waybill,
            epl_title_number=title,
            performed_at=NOW,
            snapshot={"driver": {"full_name": "Ефимов"}},
            organization_id=w.org.id,
            specialist_user_id=w.medic.id,
            phase=InspectionPhase.PRE if title == 2 else InspectionPhase.POST,
            driver_id=w.driver.id,
            complaints="отсутствуют",
            bp_systolic=120,
            bp_diastolic=80,
            pulse=70,
            temperature=36.6,
            alcohol_mgl=0,
            harmful_factors=HarmfulFactors.ABSENT,
            result=InspectionResult.ADMITTED,
        )
    )
    session.add(
        InboxEvent(
            event_id=uuid.uuid4(),
            event_type=f"T{title}",
            payload={
                "waybill_id": str(waybill),
                "event_type": f"T{title}",
                "harmful_factors_detected": flag,
            },
        )
    )
    await session.commit()
    rec = (
        await session.execute(select(MedicalRecord).where(MedicalRecord.epl_waybill_id == waybill))
    ).scalar_one()
    return rec.id


async def test_repair_fixes_only_unknown_and_leaves_journal_records(session: AsyncSession) -> None:
    """Исправляются только записи, где событие не содержало признака; «в журнале» не трогаем."""
    w = await seed(session)
    wrong = await _epl_record(session, w, flag=None, status=RecordStatus.SIGNED)
    truly_absent = await _epl_record(session, w, flag=False, status=RecordStatus.SIGNED)
    in_journal = await _epl_record(session, w, flag=None, status=RecordStatus.IN_JOURNAL, title=6)

    preview = await repair(session, apply=False)
    assert preview.found == 2 and preview.fixed == 0 and preview.in_journal == [in_journal]
    assert (
        await session.get(MedicalRecord, wrong, populate_existing=True)
    ).harmful_factors is HarmfulFactors.ABSENT

    done = await repair(session, apply=True)
    assert done.fixed == 1
    state = {
        r.id: r.harmful_factors for r in (await session.execute(select(MedicalRecord))).scalars()
    }
    assert state[wrong] is None
    assert (
        state[truly_absent] is HarmfulFactors.ABSENT
    )  # событие действительно говорило «отсутствуют»
    assert state[in_journal] is HarmfulFactors.ABSENT  # подписанный журнал не меняется
    audit = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "repair.harmful_factors_unknown")
        )
    ).scalar_one()
    assert audit.payload == {"fixed": 1, "left_in_journal": 1}


async def test_repair_is_idempotent_and_restores_the_trigger(session: AsyncSession) -> None:
    """Повторный запуск ничего не делает; защита подписанных записей после правки снова включена."""
    w = await seed(session)
    rid = await _epl_record(session, w, flag=None, status=RecordStatus.SIGNED)
    assert (await repair(session, apply=True)).fixed == 1
    again = await repair(session, apply=True)
    assert again.found == 0 and again.fixed == 0
    with pytest.raises(DBAPIError):
        await session.execute(
            update(MedicalRecord).where(MedicalRecord.id == rid).values(pulse=99)
        )
        await session.commit()
    await session.rollback()
    enabled = (
        await session.execute(
            text("SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_medical_records_immutable'")
        )
    ).scalar_one()
    assert enabled in ("O", b"O")  # триггер включён


async def test_audit_verification_command_detects_tampering(session: AsyncSession) -> None:
    """Потоковая проверка аудита: цела на честных данных и находит подмену (в обход триггера)."""
    from app.maintenance.verify_audit import verify_stream
    from app.modules.audit.service import append_audit

    for n in range(5):
        await append_audit(
            session, None, action=f"test.{n}", entity_type="medical", payload={"n": n}
        )
    await session.commit()
    healthy = await verify_stream(session, batch=2)
    assert healthy.ok and healthy.checked == 5
    await session.commit()  # завершаем транзакцию проверки: подмена идёт отдельным соединением

    # Злоумышленник с правами владельца таблицы отключает триггер и правит запись.
    await session.execute(text("ALTER TABLE audit_log DISABLE TRIGGER trg_audit_log_immutable"))
    await session.execute(
        text("UPDATE audit_log SET actor_role = 'superadmin' WHERE action = 'test.3'")
    )
    await session.execute(text("ALTER TABLE audit_log ENABLE TRIGGER trg_audit_log_immutable"))
    await session.commit()
    broken = await verify_stream(session, batch=2)
    assert not broken.ok and broken.checked == 3 and "содержимым" in (broken.reason or "")


async def test_storage_verification_finds_missing_and_corrupted_files(
    session: AsyncSession, storage
) -> None:
    """Сверка файлов с БД: целое хранилище проходит, пропавший и подменённый файлы находятся."""
    from sqlalchemy import select as sa_select

    from app.domain.enums import JournalKind
    from app.maintenance.verify_storage import verify_storage
    from app.models.documents import RecordDocument
    from tests.integration.test_flows import _signed_record

    w = await seed(session)
    for _ in range(3):
        await _signed_record(session, w, storage)
    clean = await verify_storage(session, storage)
    assert (
        clean.ok and clean.documents == 3 and clean.files >= 12
    )  # xml, pdf, подпись, метка времени

    docs = (await session.execute(sa_select(RecordDocument))).scalars().all()
    await storage.put(docs[0].xml_key or "", "<подменено/>".encode())
    await storage.delete(docs[1].pdf_key or "")
    broken = await verify_storage(session, storage)
    assert not broken.ok
    assert len(broken.corrupted) == 1 and docs[0].xml_key in broken.corrupted[0]
    assert len(broken.missing) == 1 and docs[1].pdf_key in broken.missing[0]
    assert JournalKind.MEDICAL.value in broken.missing[0]

    sampled = await verify_storage(session, storage, sample=1)
    assert sampled.documents == 1

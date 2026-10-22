"""Электронный журнал с реальным билдером: сборка, подпись, проверка контейнера, отклонение."""

from __future__ import annotations

import base64
import io
import json
import uuid
import zipfile
from datetime import timedelta

import pytest
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.core.storage import LocalStorage
from app.domain.enums import (
    EJournalStatus,
    InspectionResult,
    JournalKind,
    RecordSource,
    RecordStatus,
    Role,
    SignatureKind,
)
from app.integrations.predreis.schemas import IntegrationEvent
from app.models.documents import RecordDocument
from app.models.records import MedicalRecord, TechnicalRecord
from app.modules.audit.service import verify_audit_export
from app.modules.ejournal.container import sha256_hex, verify_container
from app.modules.ejournal.schemas import EJournalCreate
from app.modules.ejournal.service import EJournalService
from app.modules.integration.service import IntegrationService
from app.modules.signing.service import SigningService
from app.modules.technical.schemas import TechnicalRecordCreate
from app.modules.technical.service import TechnicalService
from tests.factories import FakeSigner, World, epl_event, principal, seed
from tests.integration.test_flows import PERFORMED, _signed_record

pytestmark = pytest.mark.asyncio


async def _ingest(
    session: AsyncSession, storage: LocalStorage, event_type: str, w: World, **over: object
) -> None:
    """Принимает ЭПЛ-событие."""
    raw = epl_event(event_type, w, **over)
    await IntegrationService(session, storage).handle(
        TypeAdapter(IntegrationEvent).validate_python(raw)
    )


def _create_data(w: World, kind: JournalKind) -> EJournalCreate:
    """Параметры журнала на день осмотров."""
    return EJournalCreate(
        kind=kind,
        organization_id=w.org.id,
        period_from=PERFORMED.date(),
        period_to=PERFORMED.date(),
    )


async def _medical_world(session: AsyncSession, storage: LocalStorage) -> World:
    """Две ручные подписанные записи + две записи из ЭПЛ (одна с подписью, одна без)."""
    w = await seed(session)
    await _signed_record(session, w, storage, performed_at=PERFORMED)
    await _signed_record(session, w, storage, performed_at=PERFORMED + timedelta(hours=1))
    await _ingest(
        session,
        storage,
        "T2",
        w,
        exam_datetime=(PERFORMED + timedelta(hours=2)).replace(tzinfo=None).isoformat(),
        signature_b64=base64.b64encode(b"EPL-SIG").decode(),
        tsp_b64=base64.b64encode(b"EPL-TSP").decode(),
    )
    await _ingest(
        session,
        storage,
        "T6",
        w,
        exam_datetime=(PERFORMED + timedelta(hours=3)).replace(tzinfo=None).isoformat(),
    )
    return w


async def test_full_journal_lifecycle_produces_valid_container(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Создать → отправить → СА подписал: ZIP проходит проверку, записи в статусе В."""
    w = await _medical_world(session, storage)
    manager, sa = principal(Role.PREDREIS, w.manager.id), principal(Role.SA)
    signer = FakeSigner()
    svc = EJournalService(session, signer, storage=storage)

    draft = await svc.create(manager, _create_data(w, JournalKind.MEDICAL))
    assert draft.record_count == 4
    awaiting = await svc.submit(manager, draft.id)
    assert awaiting.status is EJournalStatus.AWAITING_SIGNATURE
    assert awaiting.package and awaiting.xml_sha256 and awaiting.preview_pdf_key
    assert (await storage.get(awaiting.preview_pdf_key)).startswith(b"%PDF")
    staged_xml = await storage.get(awaiting.xml_key or "")
    assert sha256_hex(staged_xml) == awaiting.xml_sha256

    signed = await svc.sign(sa, draft.id)
    assert signed.status is EJournalStatus.SIGNED
    # СА подписывает ровно тот journal.xml, который был подготовлен при отправке.
    name, kind = signer.calls[-1]
    assert (name, kind) == ("journal.xml", SignatureKind.ORGANIZATION)
    assert signed.cert_subject == "ООО «ПРЕДРЕЙС»" and signed.cert_serial

    zip_bytes = await storage.get(signed.zip_key or "")
    assert sha256_hex(zip_bytes) == signed.zip_sha256
    assert verify_container(zip_bytes) == []

    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = set(z.namelist())
    assert {"journal.xml", "journal.xml.sig", "journal.xml.tsp", "journal.pdf", "manifest.xml",
            "README.txt", "audit/audit-log.json"} <= names  # fmt: skip
    assert z.read("journal.xml") == staged_xml
    assert z.read("journal.xml.sig").startswith(b"SIG:")
    assert z.read("journal.pdf").startswith(b"%PDF")

    records = (await session.execute(select(MedicalRecord))).scalars().all()
    assert {r.status for r in records} == {RecordStatus.IN_JOURNAL}
    docs = {d.record_id: d for d in (await session.execute(select(RecordDocument))).scalars()}
    for rec in records:
        base = f"records/{rec.id}"
        assert f"{base}/record.xml" in names and f"{base}/record.pdf" in names
        if rec.source is RecordSource.MANUAL:
            # Подписанные байты записи не перегенерируются — иначе подпись перестала бы сходиться.
            original = await storage.get(docs[rec.id].xml_key or "")
            assert z.read(f"{base}/record.xml") == original
            assert z.read(f"{base}/record.xml.sig").startswith(b"SIG:")
            assert f"{base}/record.xml.tsp" in names
        elif docs[rec.id].sig_key:
            assert z.read(f"{base}/epl-title.sig") == b"EPL-SIG"
            assert z.read(f"{base}/epl-title.tsp") == b"EPL-TSP"
        else:
            assert f"{base}/epl-title.sig" not in names and f"{base}/record.xml.sig" not in names

    audit = z.read("audit/audit-log.json")
    assert verify_audit_export(audit) == []
    actions = {e["action"] for e in json.loads(audit)["entries"]}
    # Выгрузка фиксируется при формировании пакета — события отправки и подписи в неё не входят.
    assert {"record.create", "record.sign", "record.import_epl", "ejournal.create"} <= actions
    assert "ejournal.submit" not in actions


async def test_technical_journal_container(session: AsyncSession, storage: LocalStorage) -> None:
    """Журнал техконтроля: ручная запись механика + запись Т3 из ЭПЛ."""
    w = await seed(session)
    mech = principal(Role.MECHANIC, w.mechanic.id)
    out = await TechnicalService(session).create(
        mech,
        TechnicalRecordCreate(
            organization_id=w.org.id,
            vehicle_id=w.vehicle.id,
            performed_at=PERFORMED,
            odometer=1000,
            result=InspectionResult.ADMITTED,
        ),
    )
    res = await SigningService(session, FakeSigner(), storage).sign_records(
        mech, JournalKind.TECHNICAL, [out.id]
    )
    assert res.signed == 1
    await _ingest(
        session,
        storage,
        "T3",
        w,
        exam_datetime=(PERFORMED + timedelta(hours=1)).replace(tzinfo=None).isoformat(),
    )
    manager, sa = principal(Role.PREDREIS, w.manager.id), principal(Role.SA)
    svc = EJournalService(session, FakeSigner(), storage=storage)
    draft = await svc.create(manager, _create_data(w, JournalKind.TECHNICAL))
    await svc.submit(manager, draft.id)
    signed = await svc.sign(sa, draft.id)
    zip_bytes = await storage.get(signed.zip_key or "")
    assert verify_container(zip_bytes) == []
    techs = (await session.execute(select(TechnicalRecord))).scalars().all()
    assert len(techs) == 2 and {t.status for t in techs} == {RecordStatus.IN_JOURNAL}


async def test_submit_fails_if_record_file_was_tampered(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Подмена подписанного record.xml в хранилище обнаруживается при отправке на подпись."""
    w = await seed(session)
    await _signed_record(session, w, storage)
    doc = (await session.execute(select(RecordDocument))).scalar_one()
    await storage.put(doc.xml_key or "", b"<tampered/>")
    manager = principal(Role.PREDREIS, w.manager.id)
    svc = EJournalService(session, FakeSigner(), storage=storage)
    draft = await svc.create(manager, _create_data(w, JournalKind.MEDICAL))
    with pytest.raises(ConflictError) as exc:
        await svc.submit(manager, draft.id)
    assert exc.value.code == "storage_integrity"
    await session.rollback()
    rec = (await session.execute(select(MedicalRecord))).scalar_one()
    assert rec.reserved_journal_id is None and rec.status is RecordStatus.SIGNED


async def test_sign_fails_if_journal_xml_changed_after_submit(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Если journal.xml изменили после отправки, СА его не подпишет."""
    w = await seed(session)
    await _signed_record(session, w, storage)
    manager, sa = principal(Role.PREDREIS, w.manager.id), principal(Role.SA)
    signer = FakeSigner()
    svc = EJournalService(session, signer, storage=storage)
    draft = await svc.create(manager, _create_data(w, JournalKind.MEDICAL))
    journal = await svc.submit(manager, draft.id)
    await storage.put(journal.xml_key or "", b"<changed/>")
    with pytest.raises(ConflictError) as exc:
        await svc.sign(sa, draft.id)
    assert exc.value.code == "storage_integrity"
    await session.rollback()
    assert signer.calls == []  # подпись организации не запрашивалась


async def test_reject_removes_staged_files_but_keeps_record_files(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Отклонение удаляет подготовленный пакет, оригиналы подписанных записей остаются."""
    w = await _medical_world(session, storage)
    manager, sa = principal(Role.PREDREIS, w.manager.id), principal(Role.SA)
    svc = EJournalService(session, FakeSigner(), storage=storage)
    draft = await svc.create(manager, _create_data(w, JournalKind.MEDICAL))
    journal = await svc.submit(manager, draft.id)
    staged = [journal.xml_key, journal.preview_pdf_key, journal.audit_key]
    manual_doc = (
        (
            await session.execute(
                select(RecordDocument).where(
                    RecordDocument.sig_key.like("records/%/record.xml.sig")
                )
            )
        )
        .scalars()
        .first()
    )
    assert manual_doc and all(staged)
    for key in staged:
        assert await storage.get(key or "")

    await svc.reject(sa, draft.id, "ошибка в данных")
    for key in staged:
        with pytest.raises(FileNotFoundError):
            await storage.get(key or "")
    assert await storage.get(manual_doc.xml_key or "")
    assert journal.package is None and journal.status is EJournalStatus.REJECTED

    # Записи свободны: новый журнал собирается без ошибок.
    again = await svc.create(manager, _create_data(w, JournalKind.MEDICAL))
    await svc.submit(manager, again.id)
    assert again.status is EJournalStatus.AWAITING_SIGNATURE


async def test_journal_xml_does_not_leak_when_no_epl_signature(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Запись из ЭПЛ без файла подписи попадает в журнал без Signature, но с метаданными в записи."""
    w = await seed(session)
    await _ingest(session, storage, "T2", w)
    manager = principal(Role.PREDREIS, w.manager.id)
    svc = EJournalService(session, FakeSigner(), storage=storage)
    draft = await svc.create(manager, _create_data(w, JournalKind.MEDICAL))
    journal = await svc.submit(manager, draft.id)
    xml = await storage.get(journal.xml_key or "")
    assert b"<Signature" not in xml and b'source="epl"' in xml
    assert uuid.UUID(str(journal.id))

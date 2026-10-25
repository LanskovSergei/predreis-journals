"""Сквозные сценарии на реальном PostgreSQL: жизненный цикл записи, триггеры, ЭПЛ, журналы."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    ForbiddenError,
    ValidationFailedError,
)
from app.core.storage import LocalStorage
from app.domain.enums import (
    DeletionStatus,
    EJournalStatus,
    HarmfulFactors,
    InspectionPhase,
    InspectionResult,
    JournalKind,
    RecordSource,
    RecordStatus,
    Role,
)
from app.integrations.predreis.schemas import EplRecordEvent
from app.models.catalog import Organization, User
from app.models.documents import EJournal, RecordDocument
from app.models.integration import InboxEvent
from app.models.records import MedicalRecord, TechnicalRecord
from app.modules.audit.service import verify_chain
from app.modules.deletion.service import DeletionService
from app.modules.ejournal.schemas import EJournalCreate
from app.modules.ejournal.service import EJournalService
from app.modules.integration.service import IntegrationService
from app.modules.medical.schemas import (
    MedicalRecordClientOut,
    MedicalRecordCreate,
    MedicalRecordOut,
    MedicalRecordUpdate,
)
from app.modules.medical.service import MedicalService
from app.modules.records.schemas import MedicalFilters, PageParams, TechnicalFilters
from app.modules.reports.service import ExportRequest, ReportService
from app.modules.signing.service import SigningService
from app.modules.technical.schemas import TechnicalRecordCreate
from app.modules.technical.service import TechnicalService
from tests.factories import (
    FakeSigner,
    World,
    epl_event,
    principal,
    seed,
    sign_records_now,
)

pytestmark = pytest.mark.asyncio
PERFORMED = datetime(2026, 10, 14, 8, 20, tzinfo=timezone(timedelta(hours=3)))
PAGE = PageParams(page=1, page_size=10)


class NoopBuilder:
    """Строитель без реальной сборки: сохраняет лишь заготовку journal.xml для проверки состояний."""

    def __init__(self, storage: LocalStorage) -> None:
        """Запоминает хранилище, куда кладётся заготовка."""
        self.storage = storage

    async def build_package(self, journal: EJournal, records: object) -> None:
        """Готовит минимальный пакет: файл journal.xml и его хеш."""
        data = b"<journal/>"
        journal.xml_key = await self.storage.put(f"journals/{journal.id}/journal.xml", data)
        journal.xml_sha256 = hashlib.sha256(data).hexdigest()

    async def finalize(self, journal: object, result: object) -> None:
        """Ничего не собирает."""

    def discard(self, journal: object) -> list[str]:
        """Нечего сбрасывать."""
        return []

    async def delete_files(self, keys: object) -> None:
        """Нечего удалять."""


def _medical_data(w: World, **over: object) -> MedicalRecordCreate:
    """Корректные данные медосмотра."""
    base = {
        "organization_id": w.org.id,
        "driver_id": w.driver.id,
        "phase": InspectionPhase.PRE,
        "performed_at": PERFORMED,
        "bp_systolic": 137,
        "bp_diastolic": 84,
        "pulse": 72,
        "temperature": "36.6",
        "harmful_factors": HarmfulFactors.ABSENT,
        "result": InspectionResult.ADMITTED,
    }
    return MedicalRecordCreate(**{**base, **over})  # type: ignore[arg-type]


async def _signed_record(
    session: AsyncSession, w: World, storage: LocalStorage, **over: object
) -> uuid.UUID:
    """Создаёт запись медосмотра, подписывает её (воркер подписи отрабатывает сразу), возвращает id."""
    medic = principal(Role.MEDIC, w.medic.id)
    out = await MedicalService(session).create(medic, _medical_data(w, **over))
    res = await sign_records_now(
        session, FakeSigner(), storage, medic, JournalKind.MEDICAL, [out.id]
    )
    assert res.signed == 1, res
    return out.id


async def test_full_record_lifecycle_and_immutability(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """А → Б: подпись создаёт документ и файлы; дальше правка невозможна ни в сервисе, ни в БД."""
    w = await seed(session)
    medic = principal(Role.MEDIC, w.medic.id)
    svc = MedicalService(session)
    out = await svc.create(medic, _medical_data(w))
    assert isinstance(out, MedicalRecordOut)
    assert out.status is RecordStatus.UNSIGNED
    assert {"edit", "delete", "sign"} <= set(out.actions)

    signer = FakeSigner()
    res = await sign_records_now(session, signer, storage, medic, JournalKind.MEDICAL, [out.id])
    assert res.signed == 1 and res.failed == 0
    # Предрейс получает XML на подпись сертификатом именно этого специалиста.
    call = signer.calls[0]
    assert call.document_type == "journal.medical_exam" and call.signer_user_id == w.medic.id
    assert call.content.startswith(b"<?xml")

    got = await svc.get_out(medic, out.id)
    assert got.status is RecordStatus.SIGNED
    assert got.signature and got.signature.cert_serial
    doc = (await session.execute(select(RecordDocument))).scalar_one()
    for key in (doc.xml_key, doc.pdf_key, doc.sig_key, doc.tsp_key):
        assert key and await storage.get(key)
    assert (await storage.get(doc.pdf_key or "")).startswith(b"%PDF")

    with pytest.raises(ConflictError):
        await svc.update(medic, out.id, MedicalRecordUpdate(pulse=70))
    # Триггер БД защищает и от обхода сервиса.
    with pytest.raises(DBAPIError):
        await session.execute(
            text("UPDATE medical_records SET pulse = 99 WHERE id = :i"), {"i": out.id}
        )
    await session.rollback()
    assert await verify_chain(session)


async def test_only_record_specialist_can_sign(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Чужую запись подписать нельзя: массовая подпись возвращает ошибку по этой записи."""
    w = await seed(session)
    out = await MedicalService(session).create(
        principal(Role.PREDREIS, w.manager.id), _medical_data(w, specialist_user_id=w.medic.id)
    )
    other_medic = principal(Role.MEDIC, uuid.uuid4())
    res = await SigningService(session, FakeSigner(), storage).request_signing(
        other_medic, JournalKind.MEDICAL, [out.id]
    )
    assert res.failed == 1
    assert res.results[0].code == "not_record_specialist"
    with pytest.raises(ForbiddenError):
        await SigningService(session, FakeSigner(), storage).request_signing(
            principal(Role.PREDREIS, w.manager.id), JournalKind.MEDICAL, [out.id]
        )


async def test_note_blocks_signing_until_cleared(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Запись с примечанием не подписывается; после «Снять примечание» — подписывается."""
    w = await seed(session)
    medic = principal(Role.MEDIC, w.medic.id)
    svc = MedicalService(session)
    out = await svc.create(medic, _medical_data(w, note="Сверить пульс"))
    assert out.has_note and "sign" not in out.actions
    gateway = FakeSigner()
    first = await sign_records_now(session, gateway, storage, medic, JournalKind.MEDICAL, [out.id])
    assert first.results[0].code == "note_not_empty"
    cleared = await svc.clear_note_out(medic, out.id)
    assert not cleared.has_note and "sign" in cleared.actions
    second = await sign_records_now(
        session, gateway, storage, medic, JournalKind.MEDICAL, [out.id]
    )
    assert second.signed == 1


async def test_specialist_cannot_create_for_someone_else(session: AsyncSession) -> None:
    """Медик создаёт записи только от своего имени."""
    w = await seed(session)
    with pytest.raises(ForbiddenError):
        await MedicalService(session).create(
            principal(Role.MEDIC, w.medic.id), _medical_data(w, specialist_user_id=uuid.uuid4())
        )


async def test_filters_pagination_and_client_masking(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Клиент ЭПЛ-организации видит только подписанные записи и без медицинских показателей."""
    w = await seed(session)
    for day in range(12):
        await MedicalService(session).create(
            principal(Role.MEDIC, w.medic.id),
            _medical_data(w, performed_at=PERFORMED + timedelta(days=day)),
        )
    signed_id = await _signed_record(
        session, w, storage, performed_at=PERFORMED + timedelta(days=20)
    )

    manager = principal(Role.PREDREIS, w.manager.id)
    svc = MedicalService(session)
    page1 = await svc.list_records(manager, MedicalFilters(), PAGE)
    assert page1.total == 13 and len(page1.items) == 10
    assert page1.items[0].performed_at > page1.items[-1].performed_at  # сначала новые
    only_signed = await svc.list_records(manager, MedicalFilters(is_signed=True), PAGE)
    assert only_signed.total == 1
    by_name = await svc.list_records(manager, MedicalFilters(driver_name="ефимов"), PAGE)
    assert by_name.total == 13

    client = principal(Role.CLIENT, org_id=w.org.id)
    listing = await svc.list_records(client, MedicalFilters(), PAGE)
    assert listing.total == 1
    item = listing.items[0]
    assert isinstance(item, MedicalRecordClientOut)
    assert item.id == signed_id
    dumped = item.model_dump()
    for secret in (
        "complaints",
        "bp_systolic",
        "pulse",
        "temperature",
        "alcohol_mgl",
        "harmful_factors",
    ):
        assert secret not in dumped

    other_client = principal(Role.CLIENT, org_id=uuid.uuid4())
    with pytest.raises(ForbiddenError):
        await svc.list_records(other_client, MedicalFilters(), PAGE)


async def test_client_of_paper_organization_has_no_access(session: AsyncSession) -> None:
    """Клиент вне ЭПЛ (бумажные ПЛ) доступа к журналам не имеет."""
    from app.domain.enums import WorkFormat

    w = await seed(session, WorkFormat.PAPER)
    with pytest.raises(ForbiddenError):
        await MedicalService(session).list_records(
            principal(Role.CLIENT, org_id=w.org.id), MedicalFilters(), PAGE
        )


async def test_odometer_issue_adds_note(session: AsyncSession) -> None:
    """Одометр меньше предыдущего выезда → в «Примечание» ставится метка."""
    w = await seed(session)
    mech = principal(Role.MECHANIC, w.mechanic.id)
    svc = TechnicalService(session)
    base = {
        "organization_id": w.org.id,
        "vehicle_id": w.vehicle.id,
        "result": InspectionResult.ADMITTED,
    }
    first = await svc.create(
        mech, TechnicalRecordCreate(**base, performed_at=PERFORMED, odometer=1000)
    )
    assert not first.has_note
    second = await svc.create(
        mech,
        TechnicalRecordCreate(**base, performed_at=PERFORMED + timedelta(days=1), odometer=900),
    )
    assert second.has_note and "Одометр" in (second.note or "")
    listing = await svc.list_records(mech, TechnicalFilters(plate="224ек"), PAGE)
    assert listing.total == 2


async def test_deletion_request_flow(session: AsyncSession, storage: LocalStorage) -> None:
    """Предрейс запрашивает удаление, Админ подтверждает: запись и файлы удалены."""
    w = await seed(session)
    rid = await _signed_record(session, w, storage)
    manager = principal(Role.PREDREIS, w.manager.id)
    admin = principal(Role.ADMIN)
    svc = MedicalService(session)

    with pytest.raises(ForbiddenError):
        await svc.request_deletion(principal(Role.MEDIC, w.medic.id), rid, "x")
    req = await svc.request_deletion(manager, rid, "ошибка ввода")
    with pytest.raises(ConflictError):
        await svc.request_deletion(manager, rid, "повтор")
    rec = await svc.get(manager, rid)
    assert rec.deletion_pending

    doc = (await session.execute(select(RecordDocument))).scalar_one()
    keys = [k for k in (doc.xml_key, doc.pdf_key, doc.sig_key) if k]
    with pytest.raises(ForbiddenError):
        await DeletionService(session, storage).approve(manager, req.id, None)
    done = await DeletionService(session, storage).approve(admin, req.id, "ок")
    assert done.status is DeletionStatus.APPROVED
    assert (
        await session.execute(select(func.count()).select_from(MedicalRecord))
    ).scalar_one() == 0
    for key in keys:
        with pytest.raises(FileNotFoundError):
            await storage.get(key)


async def test_deletion_rejected_restores_record(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Отклонённый запрос снимает флаг «на удалении»."""
    w = await seed(session)
    rid = await _signed_record(session, w, storage)
    manager = principal(Role.PREDREIS, w.manager.id)
    req = await MedicalService(session).request_deletion(manager, rid, None)
    await DeletionService(session, storage).reject(principal(Role.SA), req.id, "нет")
    assert not (await MedicalService(session).get(manager, rid)).deletion_pending


async def test_epl_ingestion_is_idempotent_and_immutable(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """ЭПЛ-запись: создаётся как Б, снимок — из события, реплики не затираются, дублей нет."""
    w = await seed(session)
    raw = epl_event("T2", w, notes="Проверено повторно")
    event = EplRecordEvent.model_validate(raw)
    svc = IntegrationService(session, storage)
    assert await svc.handle(event) == "processed"
    assert await svc.handle(event) == "duplicate"
    # Новое event_id, но тот же титул той же накладной — запись не дублируется.
    again = EplRecordEvent.model_validate({**raw, "event_id": str(uuid.uuid4())})
    assert await svc.handle(again) == "processed"

    rec = (await session.execute(select(MedicalRecord))).scalar_one()
    assert rec.source is RecordSource.EPL and rec.status is RecordStatus.SIGNED
    assert rec.phase is InspectionPhase.PRE
    assert rec.specialist_user_id == w.medic.id
    assert rec.gis_uid == raw["gis_uid"] and rec.waybill_number == raw["waybill_number"]
    assert rec.note == "Проверено повторно"
    # Момент осмотра сохранён верно (БД отдаёт timestamptz в UTC): 08:20 +03:00 = 05:20 UTC.
    assert rec.performed_at == datetime(2026, 10, 14, 8, 20, tzinfo=timezone(timedelta(hours=3)))
    assert rec.epl_details and rec.epl_details["critical_flag"] is False
    assert rec.epl_details["medic_license_number"] == "01162"
    # Снимок — реквизиты на момент осмотра, а не текущие из реплики.
    assert rec.snapshot["organization"]["name"] == "ООО «Название на момент осмотра»"
    assert rec.snapshot["organization"]["name"] != w.org.name
    assert rec.snapshot["driver"]["full_name"] == "Ефимов Андрей Константинович"
    assert rec.snapshot["driver"]["gender"] == "M"
    # Событие не затирает реплики: доступ специалиста к журналам сохранён.
    medic = (await session.execute(select(User).where(User.id == w.medic.id))).scalar_one()
    assert medic.journals_access is True
    org = (await session.execute(select(Organization))).scalar_one()
    assert org.name == w.org.name and org.work_format is w.org.work_format

    manager = principal(Role.PREDREIS)
    out = await MedicalService(session).get_out(manager, rec.id)
    assert out.actions == []  # ни править, ни удалять, ни подписывать
    with pytest.raises(ConflictError):
        await MedicalService(session).request_deletion(manager, rec.id, None)
    with pytest.raises(DBAPIError):
        await session.execute(text("DELETE FROM medical_records"))
    await session.rollback()


async def test_epl_medical_mapping(session: AsyncSession, storage: LocalStorage) -> None:
    """Т6 → послерейсовый; «не допущен» и вредные факторы переносятся в запись."""
    w = await seed(session)
    raw = epl_event(
        "T6",
        w,
        approved=False,
        harmful_factors_detected=True,
        harmful_factors=["признаки опьянения"],
        alcohol_ppm="0.35",
    )
    ev = EplRecordEvent.model_validate(raw)
    await IntegrationService(session, storage).handle(ev)
    rec = (await session.execute(select(MedicalRecord))).scalar_one()
    assert rec.phase is InspectionPhase.POST
    assert rec.result is InspectionResult.NOT_ADMITTED
    assert rec.harmful_factors is HarmfulFactors.DETECTED
    assert rec.harmful_factors_note == "признаки опьянения"
    assert str(rec.alcohol_mgl) == "0.35"


async def test_epl_technical_title3(session: AsyncSession, storage: LocalStorage) -> None:
    """Т3 создаёт запись техконтроля; проверки тормозов/света/шин остаются в epl_details."""
    w = await seed(session)
    ev = EplRecordEvent.model_validate(epl_event("T3", w))
    assert await IntegrationService(session, storage).handle(ev) == "processed"
    rec = (await session.execute(select(TechnicalRecord))).scalar_one()
    assert rec.odometer == 1167 and rec.status is RecordStatus.SIGNED
    assert rec.vehicle_id == w.vehicle.id and rec.driver_id == w.driver.id
    assert rec.snapshot["vehicle"]["plate"] == "О224ЕК790"
    assert rec.epl_details and rec.epl_details["brakes_ok"] is True
    assert rec.epl_details["released"] is True


async def test_epl_records_produce_valid_xml(session: AsyncSession, storage: LocalStorage) -> None:
    """Записи из ЭПЛ после сохранения в БД превращаются в валидный XML по схеме."""
    from app.modules.signing.xml_builder import build_record_xml
    from app.xmlschemas import validate_xml

    w = await seed(session)
    svc = IntegrationService(session, storage)
    for title in ("T2", "T3"):
        raw = epl_event(title, w, notes="примечание из ЭПЛ")
        await svc.handle(EplRecordEvent.model_validate(raw))
    med = (await session.execute(select(MedicalRecord))).scalar_one()
    tech = (await session.execute(select(TechnicalRecord))).scalar_one()
    for kind, rec in ((JournalKind.MEDICAL, med), (JournalKind.TECHNICAL, tech)):
        data = build_record_xml(kind, rec)
        assert validate_xml(data, "record") == []
        assert b"<GisUid>7f1c1f0a" in data and b"<Source>epl</Source>" in data
    assert b"T2" in build_record_xml(JournalKind.MEDICAL, med)


async def test_epl_requires_synced_references(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Нет реплики организации/водителя/специалиста — 409, событие не фиксируется (будет повтор)."""
    ev = EplRecordEvent.model_validate(epl_event("T2"))
    svc = IntegrationService(session, storage)
    with pytest.raises(ConflictError) as exc:
        await svc.handle(ev)
    assert exc.value.code == "dependency_missing"
    await session.rollback()
    inbox = (await session.execute(select(func.count()).select_from(InboxEvent))).scalar_one()
    assert inbox == 0


async def test_epl_specialist_role_must_match_title(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Т2 подписывает медик, Т3 — механик: перепутанная роль отклоняется."""
    w = await seed(session)
    raw = epl_event("T2", w, specialist_user_id=str(w.mechanic.id))
    ev = EplRecordEvent.model_validate(raw)
    with pytest.raises(ValidationFailedError) as exc:
        await IntegrationService(session, storage).handle(ev)
    assert exc.value.code == "specialist_role_mismatch"
    await session.rollback()


async def test_epl_driver_must_belong_to_organization(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Водитель из другой организации не принимается."""
    w = await seed(session)
    other = await seed(session)
    raw = epl_event("T2", w, driver_id=str(other.driver.id))
    ev = EplRecordEvent.model_validate(raw)
    with pytest.raises(ValidationFailedError):
        await IntegrationService(session, storage).handle(ev)
    await session.rollback()


async def test_ejournal_sign_makes_records_immutable(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Журнал: создать → отправить → СА подписал → записи в статусе В и неизменяемы."""
    w = await seed(session)
    rid = await _signed_record(session, w, storage)
    manager, sa = principal(Role.PREDREIS, w.manager.id), principal(Role.SA)
    gateway = FakeSigner()
    svc = EJournalService(session, gateway, NoopBuilder(storage), storage=storage)
    data = EJournalCreate(
        kind=JournalKind.MEDICAL,
        organization_id=w.org.id,
        period_from=PERFORMED.date(),
        period_to=PERFORMED.date(),
    )
    draft = await svc.create(manager, data)
    assert draft.status is EJournalStatus.DRAFT and draft.record_count == 1
    with pytest.raises(ForbiddenError):
        await svc.sign(manager, draft.id)
    awaiting = await svc.submit(manager, draft.id)
    assert awaiting.status is EJournalStatus.AWAITING_SIGNATURE
    with pytest.raises(ConflictError):  # запись зарезервирована — на удаление уже не поставить
        await MedicalService(session).request_deletion(manager, rid, None)
    signing = await svc.sign(sa, draft.id)
    assert signing.status is EJournalStatus.SIGNING  # подпись выполняет Предрейс асинхронно
    await SigningService(session, gateway, storage, journal_finisher=svc).process_jobs()
    signed = await svc._get(draft.id)
    assert signed.status is EJournalStatus.SIGNED and signed.signed_by == sa.user_id

    rec = (await session.execute(select(MedicalRecord))).scalar_one()
    assert rec.status is RecordStatus.IN_JOURNAL
    with pytest.raises(DBAPIError):
        await session.execute(text("UPDATE medical_records SET note = 'x'"))
    await session.rollback()
    assert await verify_chain(session)


async def test_ejournal_reject_releases_records(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Отклонение журнала возвращает записи в тип Б — их можно включить в новый журнал."""
    w = await seed(session)
    await _signed_record(session, w, storage)
    manager, sa = principal(Role.PREDREIS, w.manager.id), principal(Role.SA)
    gateway = FakeSigner()
    svc = EJournalService(session, gateway, NoopBuilder(storage), storage=storage)
    data = EJournalCreate(
        kind=JournalKind.MEDICAL,
        organization_id=w.org.id,
        period_from=PERFORMED.date(),
        period_to=PERFORMED.date(),
    )
    j1 = await svc.create(manager, data)
    await svc.submit(manager, j1.id)
    rejected = await svc.reject(sa, j1.id, "ошибка")
    assert rejected.status is EJournalStatus.REJECTED
    rec = (await session.execute(select(MedicalRecord))).scalar_one()
    assert rec.status is RecordStatus.SIGNED and rec.reserved_journal_id is None
    j2 = await svc.create(manager, data)
    assert j2.record_count == 1


async def test_pdf_export_for_client_and_manager(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Выгрузка PDF: имя файла по ТЗ, клиент ограничен своей организацией."""
    w = await seed(session)
    await _signed_record(session, w, storage)
    req = ExportRequest(
        organization_id=w.org.id, date_from=PERFORMED.date(), date_to=PERFORMED.date()
    )
    pdf, name = await ReportService(session).registry_pdf(
        principal(Role.CLIENT, org_id=w.org.id), JournalKind.MEDICAL, req
    )
    assert pdf.startswith(b"%PDF")
    assert name == "Отчёт о медосмотрах ПРЕДРЕЙС_с 14.10.2026 по 14.10.2026.pdf"
    with pytest.raises(ForbiddenError):  # механик не экспортирует журнал медосмотров
        await ReportService(session).registry_pdf(
            principal(Role.MECHANIC), JournalKind.MEDICAL, req
        )

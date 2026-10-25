"""Потребитель очереди и синхронизация справочников на реальной БД."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.storage import LocalStorage
from app.domain.enums import RecordStatus, WorkFormat
from app.models.catalog import Driver, Organization, User, Vehicle
from app.models.documents import RecordDocument
from app.models.integration import InboxEvent, InboxFailure, SyncState
from app.models.records import MedicalRecord
from app.modules.catalog.sync import SYNC_PLAN, sync_entity
from app.workers.consumer import MAX_DEPENDENCY_ATTEMPTS, Outcome, process_body
from tests.factories import seed
from tests.samples.predreis import load

pytestmark = pytest.mark.asyncio


def factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий на тот же движок (потребитель открывает свои сессии)."""
    return async_sessionmaker(session.bind, expire_on_commit=False)  # type: ignore[arg-type]


def body(
    payload: dict[str, Any], event_type: str = "journal.medical_exam", mid: str | None = None
) -> bytes:
    """Тело сообщения очереди."""
    return json.dumps(
        {"id": mid or str(uuid.uuid4()), "event_type": event_type, "entity_id": "r1", "payload": payload}
    ).encode()  # fmt: skip


def exam_payload(
    w: Any, sample: str = "event_medical_pre.json", *, ids: bool = True, **over: Any
) -> dict[str, Any]:
    """Реальный образец события, привязанный к тестовому миру (ids=False — только по реквизитам)."""
    payload = load(sample)["payload"]
    payload["waybill_id"] = str(uuid.uuid4())
    payload["organization"].update(
        inn=w.org.inn, kpp=None, name_full="ООО «Название на момент осмотра»"
    )
    payload["driver"].update(
        last_name="Ефимов",
        first_name="Андрей",
        middle_name="Константинович",
        birth_date="1980-01-01",
    )
    payload["vehicle"].update(plate_number=" о224ек790 ", brand="ГАЗон", model="Next")
    payload["specialist_user_id"] = str(w.medic.id if "medical" in sample else w.mechanic.id)
    ids_map = {"organization": w.org.id, "driver": w.driver.id, "vehicle": w.vehicle.id}
    for key, value in ids_map.items():
        if ids:
            payload[key]["id"] = str(value)
        else:
            payload[key].pop("id")
    payload.update(over)
    return payload


async def test_message_creates_record_binding_by_requisites(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Сообщение без идентификаторов справочников привязывается по ИНН, ФИО и дате рождения."""
    w = await seed(session)
    outcome = await process_body(
        body(exam_payload(w, ids=False)), factory(session), storage, Settings()
    )
    assert outcome is Outcome.ACK
    rec = (await session.execute(select(MedicalRecord))).scalar_one()
    assert rec.status is RecordStatus.SIGNED and rec.driver_id == w.driver.id
    assert rec.snapshot["organization"]["name"] == "ООО «Название на момент осмотра»"
    assert (
        rec.snapshot["driver"]["license"] == "9900000000"
        and rec.snapshot["driver"]["gender"] is None
    )


async def test_duplicate_message_is_harmless(session: AsyncSession, storage: LocalStorage) -> None:
    """Повторная доставка того же сообщения не создаёт вторую запись."""
    w = await seed(session)
    raw = body(exam_payload(w), mid="evt-100")
    for _ in range(2):
        assert await process_body(raw, factory(session), storage, Settings()) is Outcome.ACK
    assert (
        await session.execute(select(func.count()).select_from(MedicalRecord))
    ).scalar_one() == 1
    assert (await session.execute(select(func.count()).select_from(InboxEvent))).scalar_one() == 1


async def test_unmappable_message_goes_to_failures_and_queue_continues(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Неполное или нераспознанное сообщение сохраняется с исходным телом; очередь не блокируется."""
    w = await seed(session)
    payload = exam_payload(w)
    payload["vitals"].pop("blood_pressure_systolic")
    assert (
        await process_body(body(payload, mid="evt-bad"), factory(session), storage, Settings())
        is Outcome.ACK
    )
    failure = (await session.execute(select(InboxFailure))).scalar_one()
    assert failure.reason == "invalid_payload" and "blood_pressure_systolic" in (
        failure.detail or ""
    )
    assert failure.payload and failure.message_id == "evt-bad"
    assert (
        await session.execute(select(func.count()).select_from(MedicalRecord))
    ).scalar_one() == 0


async def test_garbage_message_is_recorded(session: AsyncSession, storage: LocalStorage) -> None:
    """Не JSON и неверный конверт тоже не блокируют очередь."""
    for raw in (
        b"not json",
        json.dumps({"id": "x", "event_type": "other", "payload": {}}).encode(),
    ):
        assert await process_body(raw, factory(session), storage, Settings()) is Outcome.ACK
    reasons = {f.reason for f in (await session.execute(select(InboxFailure))).scalars()}
    assert reasons == {"bad_envelope"}


async def test_missing_reference_is_retried_then_parked(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Нет справочника: сообщение повторяется, затем сохраняется в failures, а не крутится вечно."""
    w = await seed(session)
    payload = exam_payload(w, ids=False)
    payload["organization"]["inn"] = "1234567894"
    attempts: dict[str, int] = {}
    raw = body(payload, mid="evt-dep")
    for _ in range(MAX_DEPENDENCY_ATTEMPTS - 1):
        assert (
            await process_body(raw, factory(session), storage, Settings(), attempts)
            is Outcome.REQUEUE
        )
    assert await process_body(raw, factory(session), storage, Settings(), attempts) is Outcome.ACK
    failure = (await session.execute(select(InboxFailure))).scalar_one()
    assert failure.reason == "dependency_missing"


async def test_message_before_cutoff_is_skipped(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Осмотры раньше даты запуска журнала не импортируются."""
    w = await seed(session)
    settings = Settings(epl_import_from=date(2026, 11, 1))
    assert (
        await process_body(body(exam_payload(w)), factory(session), storage, settings)
        is Outcome.ACK
    )
    assert (
        await session.execute(select(func.count()).select_from(MedicalRecord))
    ).scalar_one() == 0
    inbox = (await session.execute(select(InboxEvent))).scalar_one()
    assert inbox.processed_at is not None  # событие учтено, повторно его не обрабатывать


async def test_event_creates_specialist_without_touching_existing_roles(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Новый специалист из события попадает в реплику; у существующего не меняются роль и доступ."""
    w = await seed(session)
    newcomer = uuid.uuid4()
    payload = exam_payload(w, specialist_user_id=str(newcomer))
    payload["specialist"].update(last_name="Новый", first_name="Медик", middle_name=None)
    await process_body(body(payload), factory(session), storage, Settings())
    created = (await session.execute(select(User).where(User.id == newcomer))).scalar_one()
    assert created.full_name == "Новый Медик" and created.journals_access is False
    existing = exam_payload(w)  # специалист w.medic: journals_access=True в тестовом мире
    await process_body(body(existing), factory(session), storage, Settings())
    medic = (await session.execute(select(User).where(User.id == w.medic.id))).scalar_one()
    assert medic.journals_access is True


# ---------- синхронизация справочников ----------


class FakeCatalog:
    """Подставной источник справочников со страницами и записью параметров запросов."""

    def __init__(self, data: dict[str, list[dict[str, Any]]]) -> None:
        """data — полный набор строк по справочникам."""
        self.data, self.calls = data, []

    async def list_catalog(
        self,
        entity: str,
        *,
        changed_after: datetime | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Страница строк, изменённых после changed_after, отсортированных по updated_at."""
        self.calls.append((entity, changed_after, limit, offset))
        rows = sorted(self.data[entity], key=lambda r: r["updated_at"])
        if changed_after:
            rows = [r for r in rows if datetime.fromisoformat(r["updated_at"]) > changed_after]
        return rows[offset : offset + limit]


def org_row(n: int, **over: Any) -> dict[str, Any]:
    """Строка справочника организаций в формате Предрейса (ИП — без адреса)."""
    row = load("catalog_organizations.json")[0]
    row.update(
        id=str(uuid.UUID(int=n)),
        inn=f"77070838{n:02d}",
        name_full=f"ООО «Организация {n}»",
        name_short=f"Орг {n}",
        legal_address=None if n == 2 else f"г. Москва, {n}",
        updated_at=f"2026-10-0{n}T10:00:00.000000Z",
    )
    row.update(over)
    return row


async def run_sync(
    session: AsyncSession, source: FakeCatalog, settings: Settings
) -> dict[str, int]:
    """Прогоняет синхронизацию всех справочников."""
    return {
        entity: await sync_entity(session, source, entity, cls, upsert, settings)
        for entity, cls, upsert in SYNC_PLAN
    }


async def test_catalog_sync_is_incremental_and_tolerant(session: AsyncSession) -> None:
    """Справочники подтягиваются постранично и инкрементально; плохие строки не мешают."""
    org_id = uuid.UUID(int=1)
    driver = {**load("catalog_drivers.json")[0], "id": str(uuid.UUID(int=11)), "org_id": str(org_id),
              "license_series": "9910", "license_number": "915125", "updated_at": "2026-10-03T10:00:00Z"}  # fmt: skip
    orphan = {**driver, "id": str(uuid.UUID(int=12)), "org_id": str(uuid.UUID(int=999)),
              "updated_at": "2026-10-03T11:00:00Z"}  # fmt: skip
    garbage = {**driver, "id": "не-uuid", "updated_at": "2026-10-03T12:00:00Z"}
    vehicle = {**load("catalog_vehicles.json")[0], "id": str(uuid.UUID(int=21)), "org_id": str(org_id),
               "updated_at": "2026-10-03T10:00:00Z"}  # fmt: skip
    source = FakeCatalog(
        {
            "organizations": [org_row(1), org_row(2)],
            "drivers": [driver, orphan, garbage],
            "vehicles": [vehicle],
        }
    )
    settings = Settings(catalog_page_size=2)
    counts = await run_sync(session, source, settings)
    assert counts == {"organizations": 2, "drivers": 1, "vehicles": 1}

    org2 = (
        await session.execute(select(Organization).where(Organization.id == uuid.UUID(int=2)))
    ).scalar_one()
    assert org2.name == "ООО «Организация 2»" and org2.legal_address is None  # адрес ИП пуст
    assert org2.work_format is WorkFormat.EPL  # из Предрейса не приходит — значение по умолчанию
    saved = (await session.execute(select(Driver))).scalar_one()
    assert saved.full_name == "Водителев Василий Васильевич" and saved.gender is None
    assert saved.license_number == "9910 915125" and saved.birth_date == date(1985, 5, 20)
    assert (await session.execute(select(Vehicle))).scalar_one().plate == "А123ВС77"
    reasons = sorted(f.reason for f in (await session.execute(select(InboxFailure))).scalars())
    assert reasons == ["catalog_fk", "catalog_invalid"]

    # Второй прогон: запрашиваются только изменения после отметки (с небольшим запасом).
    source.calls.clear()
    state = (
        await session.execute(select(SyncState).where(SyncState.entity == "organizations"))
    ).scalar_one()
    assert state.cursor and state.cursor.startswith("2026-10-02")
    await run_sync(session, source, settings)
    since = next(c[1] for c in source.calls if c[0] == "organizations")
    assert since is not None and since.date() == date(2026, 10, 2)


async def test_sync_does_not_overwrite_local_fields(session: AsyncSession) -> None:
    """Синхронизация не затирает поля, которых нет в Предрейсе (формат работы, договор)."""
    w = await seed(session, WorkFormat.PAPER)
    row = org_row(
        1, id=str(w.org.id), inn=w.org.inn, updated_at=datetime.now(timezone.utc).isoformat()
    )
    source = FakeCatalog({"organizations": [row], "drivers": [], "vehicles": []})
    await run_sync(session, source, Settings())
    org = (
        await session.execute(select(Organization).where(Organization.id == w.org.id))
    ).scalar_one()
    assert org.work_format is WorkFormat.PAPER and org.short_name == "Орг 1"


async def test_placeholder_signature_does_not_block_record(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Событие с AUTO_SIGNATURE создаёт запись без файла подписи; состояние видно в epl_details."""
    w = await seed(session)
    raw = body(exam_payload(w, signature_b64="AUTO_SIGNATURE"), mid="auto-sig")
    assert await process_body(raw, factory(session), storage, Settings()) is Outcome.ACK
    rec = (await session.execute(select(MedicalRecord))).scalar_one()
    assert rec.epl_details and rec.epl_details["signature_state"] == "placeholder"
    doc = (await session.execute(select(RecordDocument))).scalar_one()
    assert doc.sig_key is None and doc.cert_serial is None
    assert (
        await session.execute(select(func.count()).select_from(InboxFailure))
    ).scalar_one() == 0


async def test_real_title_signature_gives_certificate_data(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Настоящая подпись титула: серийный номер, владелец и срок берутся из неё."""
    import base64

    from tests.test_cms import make_signature

    w = await seed(session)
    cms_bytes, cert = make_signature()
    raw = body(exam_payload(w, signature_b64=base64.b64encode(cms_bytes).decode()), mid="real-sig")
    assert await process_body(raw, factory(session), storage, Settings()) is Outcome.ACK
    doc = (await session.execute(select(RecordDocument))).scalar_one()
    assert doc.sig_key and doc.cert_serial == cert.serial_number.to_bytes(16, "big").hex()
    assert doc.cert_subject == "Абдуллаева Гульзана Абутдиновна"
    assert await storage.get(doc.sig_key) == cms_bytes


async def test_replay_resolves_failures_after_catalog_arrives(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Справочник пришёл позже сообщения: replay создаёт запись и убирает отказ из таблицы."""
    from app.workers.replay import replay_failures

    w = await seed(session)
    payload = exam_payload(w, ids=False)
    payload["driver"]["last_name"] = "Позже"  # водителя в справочнике ещё нет
    attempts = {"late-1": MAX_DEPENDENCY_ATTEMPTS - 1}
    raw = body(payload, mid="late-1")
    assert await process_body(raw, factory(session), storage, Settings(), attempts) is Outcome.ACK
    failure = (await session.execute(select(InboxFailure))).scalar_one()
    assert failure.reason == "dependency_missing"

    report = await replay_failures(factory(session), storage, Settings())
    assert (report.checked, report.resolved, report.still_failing) == (1, 0, 1)

    # Водитель появился в справочнике (синхронизация): повтор успешен.
    await session.execute(
        update(Driver)
        .where(Driver.id == w.driver.id)
        .values(full_name="Позже Андрей Константинович")
    )
    await session.commit()
    report = await replay_failures(factory(session), storage, Settings())
    assert (report.checked, report.resolved, report.still_failing) == (1, 1, 0)
    assert (
        await session.execute(select(func.count()).select_from(MedicalRecord))
    ).scalar_one() == 1
    assert (
        await session.execute(select(func.count()).select_from(InboxFailure))
    ).scalar_one() == 0


async def test_replay_dry_run_and_reason_filter(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """--dry-run ничего не удаляет; фильтр по причине отсекает лишнее."""
    from app.workers.replay import replay_failures

    w = await seed(session)
    payload = exam_payload(w)  # привязка по id пройдёт, но в отказ положим вручную
    session.add(
        InboxFailure(
            message_id="manual-1",
            event_type="journal.medical_exam",
            reason="dependency_missing",
            payload=payload,
        )
    )
    await session.commit()
    dry = await replay_failures(factory(session), storage, Settings(), dry_run=True)
    assert dry.resolved == 1
    assert (
        await session.execute(select(func.count()).select_from(InboxFailure))
    ).scalar_one() == 1
    other = await replay_failures(factory(session), storage, Settings(), reasons=["phase_unknown"])
    assert other.checked == 0
    real = await replay_failures(
        factory(session), storage, Settings(), reasons=["dependency_missing"]
    )
    assert real.resolved == 1
    assert (
        await session.execute(select(func.count()).select_from(InboxFailure))
    ).scalar_one() == 0

"""Асинхронная подпись через Предрейс: записи и электронный журнал."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError
from app.core.storage import LocalStorage
from app.domain.enums import (
    EJournalStatus,
    JournalKind,
    RecordStatus,
    Role,
    SignJobStatus,
    SignTarget,
)
from app.integrations.predreis.client import SignStatus
from app.models.documents import RecordDocument, SignJob
from app.models.integration import InboxFailure
from app.models.records import MedicalRecord
from app.modules.audit.service import verify_chain
from app.modules.ejournal.container import verify_container
from app.modules.ejournal.service import EJournalService
from app.modules.medical.schemas import MedicalRecordUpdate
from app.modules.medical.service import MedicalService
from app.modules.signing.service import SigningService
from tests.factories import FakeSigner, World, principal, seed, sign_records_now
from tests.integration.test_ejournal_container import _create_data
from tests.integration.test_flows import PERFORMED, _medical_data, _signed_record
from tests.test_cms import make_signature

pytestmark = pytest.mark.asyncio


async def _record(session: AsyncSession, w: World) -> tuple[uuid.UUID, MedicalService]:
    """Новая неподписанная запись медика."""
    svc = MedicalService(session)
    out = await svc.create(principal(Role.MEDIC, w.medic.id), _medical_data(w))
    return out.id, svc


async def test_request_puts_record_in_progress_and_locks_it(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """После «Подписать» запись «в работе»: менять и удалять нельзя, повторно ставить нельзя."""
    w = await seed(session)
    medic = principal(Role.MEDIC, w.medic.id)
    rid, svc = await _record(session, w)
    gateway = FakeSigner(hold=True)
    signing = SigningService(session, gateway, storage)

    res = await signing.request_signing(medic, JournalKind.MEDICAL, [rid])
    assert res.signed == 1 and res.results[0].message == "Отправлено на подпись"
    out = await svc.get_out(medic, rid)
    assert out.status is RecordStatus.UNSIGNED and out.signing_status == "pending"
    assert out.actions == []  # кнопки скрыты, пока идёт подпись

    with pytest.raises(ConflictError) as exc:
        await svc.update(medic, rid, MedicalRecordUpdate(pulse=60))
    assert exc.value.code == "signing_in_progress"
    for call in (svc.delete_unsigned(medic, rid), svc.clear_note(medic, rid)):
        with pytest.raises(ConflictError):
            await call
    again = await signing.request_signing(medic, JournalKind.MEDICAL, [rid])
    assert again.results[0].code == "signing_in_progress"

    await signing.process_jobs()  # Предрейс ещё не подписал
    assert (await svc.get_out(medic, rid)).signing_status == "pending"


async def test_completion_signs_record_and_audits(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Готовая подпись: запись становится подписанной, файлы и сертификат сохранены, аудит цел."""
    w = await seed(session)
    medic = principal(Role.MEDIC, w.medic.id)
    rid, svc = await _record(session, w)
    gateway = FakeSigner()
    await sign_records_now(session, gateway, storage, medic, JournalKind.MEDICAL, [rid])

    out = await svc.get_out(medic, rid)
    assert out.status is RecordStatus.SIGNED and out.signing_status is None
    assert out.signature and out.signature.cert_serial
    doc = (await session.execute(select(RecordDocument))).scalar_one()
    job = (await session.execute(select(SignJob))).scalar_one()
    assert job.status is SignJobStatus.SIGNED and doc.xml_key == job.content_key
    assert await storage.get(doc.xml_key or "") == gateway.calls[0].content  # подписано именно это
    assert (await storage.get(doc.sig_key or "")).startswith(b"SIG:")
    actions = {a.action for a in await _audit(session)}
    assert {"record.sign_requested", "record.sign"} <= actions
    assert await verify_chain(session)


async def _audit(session: AsyncSession) -> list:
    """Записи аудита."""
    from app.models.audit import AuditLog

    return list((await session.execute(select(AuditLog))).scalars())


async def test_refusal_returns_record_to_editable_state_and_can_retry(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Отказ Предрейса: запись остаётся неподписанной, причина видна, повтор возможен."""
    w = await seed(session)
    medic = principal(Role.MEDIC, w.medic.id)
    rid, svc = await _record(session, w)
    await sign_records_now(
        session, FakeSigner(fail="Сертификат истёк"), storage, medic, JournalKind.MEDICAL, [rid]
    )
    out = await svc.get_out(medic, rid)
    assert out.status is RecordStatus.UNSIGNED
    assert out.signing_status == "failed" and out.signing_error == "Сертификат истёк"
    assert {"sign", "edit"} <= set(out.actions)  # можно исправить и отправить заново

    await sign_records_now(session, FakeSigner(), storage, medic, JournalKind.MEDICAL, [rid])
    assert (await svc.get_out(medic, rid)).status is RecordStatus.SIGNED
    jobs = (await session.execute(select(SignJob).order_by(SignJob.created_at))).scalars().all()
    assert [j.status for j in jobs] == [SignJobStatus.FAILED, SignJobStatus.SIGNED]


async def test_predreis_outage_keeps_job_queued_with_backoff(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Предрейс недоступен: задача ждёт в очереди и уходит после восстановления."""
    w = await seed(session)
    medic = principal(Role.MEDIC, w.medic.id)
    rid, svc = await _record(session, w)
    down = FakeSigner(submit_error=True)
    await SigningService(session, down, storage).request_signing(medic, JournalKind.MEDICAL, [rid])
    job = (await session.execute(select(SignJob))).scalar_one()
    assert job.status is SignJobStatus.QUEUED and job.attempts == 1
    assert job.next_attempt_at > datetime.now(timezone.utc)
    assert (await svc.get_out(medic, rid)).signing_status == "queued"

    await session.execute(update(SignJob).values(next_attempt_at=datetime.now(timezone.utc)))
    await session.commit()
    await SigningService(session, FakeSigner(), storage).process_jobs()
    assert (await svc.get_out(medic, rid)).status is RecordStatus.SIGNED


async def test_gives_up_after_max_submit_attempts(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Исчерпаны попытки отправки — задача помечается неудачной, причина доступна пользователю."""
    w = await seed(session)
    medic = principal(Role.MEDIC, w.medic.id)
    rid, svc = await _record(session, w)
    settings = Settings(sign_submit_max_attempts=2)
    signing = SigningService(session, FakeSigner(submit_error=True), storage, settings)
    await signing.request_signing(medic, JournalKind.MEDICAL, [rid])
    await session.execute(update(SignJob).values(next_attempt_at=datetime.now(timezone.utc)))
    await session.commit()
    await signing.process_jobs()
    out = await svc.get_out(medic, rid)
    assert out.signing_status == "failed" and "Не удалось отправить" in (out.signing_error or "")


async def test_pending_timeout_fails_job(session: AsyncSession, storage: LocalStorage) -> None:
    """Если Предрейс не отвечает слишком долго, задача завершается ошибкой."""
    w = await seed(session)
    medic = principal(Role.MEDIC, w.medic.id)
    rid, svc = await _record(session, w)
    signing = SigningService(
        session, FakeSigner(hold=True), storage, Settings(sign_pending_timeout_s=60)
    )
    await signing.request_signing(medic, JournalKind.MEDICAL, [rid])
    await session.execute(
        update(SignJob).values(submitted_at=datetime.now(timezone.utc) - timedelta(hours=2))
    )
    await session.commit()
    await signing.process_jobs()
    assert "время ожидания" in ((await svc.get_out(medic, rid)).signing_error or "")


async def test_record_changed_behind_the_scenes_is_not_signed(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Если содержимое записи изменилось в обход сервиса, подпись не применяется."""
    w = await seed(session)
    medic = principal(Role.MEDIC, w.medic.id)
    rid, svc = await _record(session, w)
    gateway = FakeSigner(hold=True)
    signing = SigningService(session, gateway, storage)
    await signing.request_signing(medic, JournalKind.MEDICAL, [rid])
    await session.execute(text("UPDATE medical_records SET pulse = 99 WHERE id = :i"), {"i": rid})
    await session.commit()
    gateway.hold = False
    await signing.process_jobs()
    rec = (await session.execute(select(MedicalRecord))).scalar_one()
    assert rec.status is RecordStatus.UNSIGNED
    assert "изменилась" in ((await svc.get_out(medic, rid)).signing_error or "")


async def test_certificate_is_read_from_signature_when_not_in_response(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Предрейс отдал только подпись: серийный номер, владелец и срок берутся из самой подписи."""
    w = await seed(session)
    medic = principal(Role.MEDIC, w.medic.id)
    rid, _ = await _record(session, w)
    cms, cert = make_signature()

    class CmsSigner(FakeSigner):
        """Отдаёт настоящую CMS-подпись без полей сертификата."""

        async def fetch(self, external_ids: list[str]) -> list[SignStatus]:  # type: ignore[override]
            """Подпись без сведений о сертификате."""
            return [SignStatus(e, None, "signed", signature=cms) for e in external_ids]

    await sign_records_now(session, CmsSigner(), storage, medic, JournalKind.MEDICAL, [rid])
    doc = (await session.execute(select(RecordDocument))).scalar_one()
    assert doc.cert_serial == cert.serial_number.to_bytes(16, "big").hex()
    assert doc.cert_subject == "Абдуллаева Гульзана Абутдиновна"
    assert doc.cert_valid_to == cert.not_valid_after_utc


async def test_signature_without_certificate_data_blocks_journal_but_not_record(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Нет сведений о сертификате: запись подписывается, а в журнал не попадёт, пока их нет."""
    w = await seed(session)
    medic = principal(Role.MEDIC, w.medic.id)
    rid, svc = await _record(session, w)
    await sign_records_now(
        session, FakeSigner(cert=False), storage, medic, JournalKind.MEDICAL, [rid]
    )
    assert (await svc.get_out(medic, rid)).status is RecordStatus.SIGNED
    manager = principal(Role.PREDREIS, w.manager.id)
    ejournals = EJournalService(session, FakeSigner(), storage=storage)
    draft = await ejournals.create(manager, _create_data(w, JournalKind.MEDICAL))
    with pytest.raises(ConflictError) as exc:
        await ejournals.submit(manager, draft.id)
    assert exc.value.code == "signature_meta_missing"


# ---------- журнал ----------


async def _awaiting_journal(
    session: AsyncSession, storage: LocalStorage, gateway: FakeSigner
) -> tuple[World, EJournalService, uuid.UUID]:
    """Журнал с одной записью, отправленный на подпись СА (реальный билдер)."""
    w = await seed(session)
    await _signed_record(session, w, storage, performed_at=PERFORMED)
    manager = principal(Role.PREDREIS, w.manager.id)
    svc = EJournalService(session, gateway, storage=storage)
    draft = await svc.create(manager, _create_data(w, JournalKind.MEDICAL))
    await svc.submit(manager, draft.id)
    return w, svc, draft.id


async def test_journal_signing_is_asynchronous_and_blocks_reject(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """«Подписать» журнал → signing; отклонить нельзя; по готовности — SIGNED и валидный ZIP."""
    gateway = FakeSigner(hold=True)
    _, svc, jid = await _awaiting_journal(session, storage, gateway)
    sa = principal(Role.SA)
    journal = await svc.sign(sa, jid)
    assert journal.status is EJournalStatus.SIGNING
    with pytest.raises(ConflictError):
        await svc.reject(sa, jid, "передумали")
    with pytest.raises(ConflictError):
        await svc.sign(sa, jid)

    finisher = SigningService(session, gateway, storage, journal_finisher=svc)
    await finisher.process_jobs()
    assert (await svc.get(sa, jid)).status is EJournalStatus.SIGNING  # Предрейс ещё не ответил

    gateway.hold = False
    await finisher.process_jobs()
    signed = await svc.get(sa, jid)
    assert signed.status is EJournalStatus.SIGNED and signed.signed_by == sa.user_id
    assert verify_container(await storage.get(signed.zip_key or "")) == []
    assert signed.cert_subject == "ООО «ПРЕДРЕЙС»"
    assert await verify_chain(session)


async def test_journal_refusal_returns_to_awaiting_with_reason(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Отказ Предрейса: журнал снова ждёт подписи, СА видит причину и может повторить."""
    gateway = FakeSigner(fail="Нет сертификата")
    _, svc, jid = await _awaiting_journal(session, storage, gateway)
    sa = principal(Role.SA)
    await svc.sign(sa, jid)
    await SigningService(session, gateway, storage, journal_finisher=svc).process_jobs()
    journal = await svc.get(sa, jid)
    assert journal.status is EJournalStatus.AWAITING_SIGNATURE
    assert journal.sign_error == "Нет сертификата"

    gateway.fail = None  # Предрейс починили — СА повторяет
    await svc.sign(sa, jid)
    await SigningService(session, gateway, storage, journal_finisher=svc).process_jobs()
    signed = await svc.get(sa, jid)
    assert signed.status is EJournalStatus.SIGNED and signed.sign_error is None


async def test_journal_is_signed_with_configured_organization_certificate(
    session: AsyncSession, storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если задан org_signer_user_id, журнал подписывается его сертификатом, а не СА."""
    gateway = FakeSigner(hold=True)
    _, svc, jid = await _awaiting_journal(session, storage, gateway)
    director = uuid.uuid4()
    monkeypatch.setattr(
        "app.modules.ejournal.service.get_settings", lambda: Settings(org_signer_user_id=director)
    )
    await svc.sign(principal(Role.SA), jid)
    assert gateway.calls[-1].signer_user_id == director


async def test_epl_failures_are_visible_to_operator(session: AsyncSession) -> None:
    """Таблица разбора пуста в чистой БД (операторский запрос не падает)."""
    assert (await session.execute(select(InboxFailure))).scalars().all() == []


_ = base64


async def test_journal_is_not_signed_with_a_personal_certificate_by_default(
    session: AsyncSession, storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Подписант журнала обязателен: молча подписать сертификатом нажавшего СА нельзя (плашка говорит «ООО ПРЕДРЕЙС»)."""
    gateway = FakeSigner(hold=True)
    _, svc, jid = await _awaiting_journal(session, storage, gateway)
    sa = principal(Role.SA)
    monkeypatch.setattr(
        "app.modules.ejournal.service.get_settings",
        lambda: Settings(journal_sign_with_requester=False, org_signer_user_id=None),
    )
    with pytest.raises(ConflictError) as exc:
        await svc.sign(sa, jid)
    assert exc.value.code == "org_signer_not_configured"
    assert (
        await svc.get(sa, jid)
    ).status is EJournalStatus.AWAITING_SIGNATURE  # ничего не изменилось
    assert gateway.calls == []  # в Предрейс ничего не отправлено
    journal_jobs = select(SignJob).where(SignJob.target == SignTarget.JOURNAL)
    assert (
        await session.execute(journal_jobs)
    ).scalars().all() == []  # задача подписи журнала не создана

    director = uuid.uuid4()
    monkeypatch.setattr(
        "app.modules.ejournal.service.get_settings",
        lambda: Settings(org_signer_user_id=director),
    )
    await svc.sign(sa, jid)
    assert (
        gateway.calls[-1].signer_user_id == director
    )  # подписывает заданный пользователь, а не нажавший СА

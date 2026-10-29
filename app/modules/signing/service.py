"""Подпись через Предрейс (асинхронная): постановка задач, отправка, опрос, завершение.

Поток: специалист нажимает «Подписать» → для записи создаётся `SignJob` (содержимое — XML,
проверенный по XSD) → воркер отправляет его в Предрейс и опрашивает результат → при успехе запись
становится подписанной (А → Б). Пока задача активна, запись нельзя менять и удалять.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.security import Principal
from app.core.storage import Storage, get_storage
from app.domain import fsm
from app.domain.enums import JournalKind, RecordStatus, SignJobStatus, SignTarget
from app.domain.permissions import RECORD_PERMS, has_permission
from app.integrations.predreis.client import SignGateway, SignResult, SignStatus
from app.integrations.predreis.cms import extract_cert_info
from app.models.documents import RecordDocument, SignJob
from app.modules.audit.service import append_audit
from app.modules.records.queries import load_record
from app.modules.records.schemas import SignBatchResult, SignOutcome
from app.modules.reports.service import render_single_record_pdf
from app.modules.signing.xml_builder import build_record_xml

logger = logging.getLogger(__name__)

RECORD_DOCUMENT_TYPES = {
    JournalKind.MEDICAL: "journal.medical_exam",
    JournalKind.TECHNICAL: "journal.technical_exam",
}
MAX_BACKOFF_S = 600


class JournalFinisher(Protocol):
    """Завершение подписи журнала (реализует EJournalService)."""

    async def finish_signing(self, job: SignJob, result: SignResult) -> None:
        """Применяет подпись: собирает ZIP, переводит записи в статус В."""

    async def fail_signing(self, job: SignJob, error: str) -> None:
        """Возвращает журнал к ожиданию подписи и сохраняет причину."""


def _sha(data: bytes) -> str:
    """SHA-256 в hex."""
    return hashlib.sha256(data).hexdigest()


def result_from_status(status: SignStatus) -> SignResult:
    """Формирует итог подписи; сведения о сертификате берутся из ответа или из самой подписи."""
    assert status.signature is not None
    return SignResult(
        signature=status.signature,
        tsp=status.tsp,
        certificate=status.certificate or extract_cert_info(status.signature),
        ocsp_status=status.ocsp_status,
        signed_at=status.signed_at or datetime.now(timezone.utc),
    )


class SigningService:
    """Постановка записей на подпись и обработка задач подписи."""

    def __init__(
        self,
        session: AsyncSession,
        gateway: SignGateway,
        storage: Storage | None = None,
        settings: Settings | None = None,
        journal_finisher: JournalFinisher | None = None,
    ) -> None:
        """Принимает сессию, шлюз подписи, хранилище, настройки и завершитель журналов."""
        self.session = session
        self.gateway = gateway
        self.storage = storage or get_storage()
        self.settings = settings or get_settings()
        self.journal_finisher = journal_finisher

    # --- постановка ---------------------------------------------------------------------------
    async def request_signing(
        self, principal: Principal, kind: JournalKind, record_ids: list[uuid.UUID]
    ) -> SignBatchResult:
        """Ставит записи в очередь на подпись; сбой одной не отменяет остальные."""
        if not has_permission(principal.role, RECORD_PERMS[kind].sign):
            raise ForbiddenError("Недостаточно прав", code="permission_denied")
        limit = self.settings.mass_sign_max_batch
        if len(record_ids) > limit:
            raise AppError(f"За один запрос можно подписать не более {limit} записей")
        results: list[SignOutcome] = []
        for record_id in dict.fromkeys(record_ids):
            try:
                await self._enqueue_record(principal, kind, record_id)
                await self.session.commit()
            except (AppError, OSError) as exc:
                await self.session.rollback()
                code = exc.code if isinstance(exc, AppError) else "storage_error"
                logger.info("Запись %s не поставлена на подпись: %s", record_id, exc)
                results.append(
                    SignOutcome(record_id=record_id, ok=False, code=code, message=str(exc))
                )
            else:
                results.append(
                    SignOutcome(record_id=record_id, ok=True, message="Отправлено на подпись")
                )
        await self.dispatch_queued()
        signed = sum(1 for r in results if r.ok)
        return SignBatchResult(signed=signed, failed=len(results) - signed, results=results)

    async def _active_job(self, subject_id: uuid.UUID) -> SignJob | None:
        """Активная (в очереди или в работе) задача подписи объекта."""
        return (
            await self.session.execute(
                select(SignJob).where(
                    SignJob.subject_id == subject_id,
                    SignJob.status.in_([SignJobStatus.QUEUED, SignJobStatus.PENDING]),
                )
            )
        ).scalar_one_or_none()

    async def _enqueue_record(
        self, principal: Principal, kind: JournalKind, record_id: uuid.UUID
    ) -> None:
        """Проверяет запись, готовит XML и создаёт задачу подписи."""
        record = await load_record(self.session, kind, record_id, for_update=True)
        if record is None:
            raise NotFoundError("Запись не найдена")
        fsm.ensure_signable(
            status=record.status,
            source=record.source,
            note=record.note,
            deletion_pending=record.deletion_pending,
            specialist_id=record.specialist_user_id,
            actor_id=principal.user_id,
        )
        if await self._active_job(record.id) is not None:
            raise ConflictError("Запись уже отправлена на подпись", code="signing_in_progress")
        xml = build_record_xml(kind, record)
        key = await self.storage.put(f"records/{kind.value}/{record.id}/record.xml", xml)
        job = SignJob(
            id=uuid.uuid4(),
            target=SignTarget.RECORD,
            journal_kind=kind,
            subject_id=record.id,
            signer_user_id=principal.user_id,
            requested_by=principal.user_id,
            document_type=RECORD_DOCUMENT_TYPES[kind],
            content_key=key,
            content_sha256=_sha(xml),
            status=SignJobStatus.QUEUED,
            external_id="",
        )
        job.external_id = str(job.id)
        self.session.add(job)
        await self.session.flush()
        await append_audit(
            self.session,
            principal,
            action="record.sign_requested",
            entity_type=kind.value,
            entity_id=str(record.id),
            payload={"job": job.external_id},
        )

    # --- обработка задач (воркер) -------------------------------------------------------------
    async def process_jobs(self) -> dict[str, int]:
        """Один проход воркера: отправить новые задачи и забрать результаты."""
        sent = await self.dispatch_queued()
        done = await self.poll_pending()
        return {"submitted": sent, "completed": done}

    async def dispatch_queued(self, limit: int = 50) -> int:
        """Отправляет в Предрейс задачи в очереди; при сбое откладывает повтор."""
        now = datetime.now(timezone.utc)
        jobs = (
            (
                await self.session.execute(
                    select(SignJob)
                    .where(SignJob.status == SignJobStatus.QUEUED, SignJob.next_attempt_at <= now)
                    .order_by(SignJob.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        sent = 0
        for job in jobs:
            try:
                content = await self.storage.get(job.content_key)
                if _sha(content) != job.content_sha256:
                    raise ConflictError(
                        "Содержимое для подписи изменилось", code="storage_integrity"
                    )
                ticket = await self.gateway.submit(
                    signer_user_id=job.signer_user_id,
                    document_type=job.document_type,
                    content=content,
                    external_id=job.external_id,
                    sign_as=job.sign_as,
                    requested_by_user_id=job.requested_by,
                )
            except (AppError, OSError) as exc:
                job.attempts += 1
                job.last_error = str(exc)[:500]
                if job.attempts >= self.settings.sign_submit_max_attempts or (
                    isinstance(exc, ConflictError)
                ):
                    await self._fail(job, f"Не удалось отправить на подпись: {exc}")
                else:
                    delay = min(5 * 2**job.attempts, MAX_BACKOFF_S)
                    job.next_attempt_at = now + timedelta(seconds=delay)
                    await self.session.commit()
                continue
            job.status = SignJobStatus.PENDING
            job.predreis_sign_id = ticket.sign_id
            job.submitted_at = datetime.now(timezone.utc)
            job.last_error = None
            await self.session.commit()
            sent += 1
        return sent

    async def poll_pending(self) -> int:
        """Опрашивает Предрейс по задачам в работе и завершает готовые."""
        jobs = (
            (
                await self.session.execute(
                    select(SignJob)
                    .where(SignJob.status == SignJobStatus.PENDING)
                    .order_by(SignJob.submitted_at)
                    .limit(self.settings.sign_poll_batch * 5)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        if not jobs:
            return 0
        try:
            statuses = {
                s.external_id: s for s in await self.gateway.fetch([j.external_id for j in jobs])
            }
        except AppError as exc:
            logger.warning("Опрос подписей не удался: %s", exc)
            await self.session.rollback()
            return 0
        completed = 0
        deadline = timedelta(seconds=self.settings.sign_pending_timeout_s)
        for job in jobs:
            job_id, external_id = job.id, job.external_id
            status = statuses.get(external_id)
            try:
                if status is not None and status.status == "signed" and status.signature:
                    if await self._complete(job, result_from_status(status)):
                        completed += 1
                elif status is not None and status.status == "failed":
                    await self._fail(job, status.error or "Предрейс отказал в подписи")
                elif job.submitted_at and datetime.now(timezone.utc) - job.submitted_at > deadline:
                    await self._fail(job, "Превышено время ожидания подписи")
            except (AppError, OSError) as exc:
                await self.session.rollback()
                logger.warning("Завершение подписи %s не удалось: %s", external_id, exc)
                fresh = await self.session.get(SignJob, job_id, populate_existing=True)
                if fresh is not None and fresh.status is SignJobStatus.PENDING:
                    await self._fail(fresh, str(exc))
        await self.session.commit()
        return completed

    async def _fail(self, job: SignJob, error: str) -> None:
        """Помечает задачу неудачной; для журнала возвращает его к ожиданию подписи."""
        job.status = SignJobStatus.FAILED
        job.last_error = error[:500]
        job.completed_at = datetime.now(timezone.utc)
        if job.target is SignTarget.JOURNAL and self.journal_finisher is not None:
            await self.journal_finisher.fail_signing(job, error[:500])
        await append_audit(
            self.session,
            None,
            action="sign.failed",
            entity_type=job.journal_kind.value,
            entity_id=str(job.subject_id),
            payload={"job": job.external_id, "error": error[:200]},
        )
        await self.session.commit()

    async def _complete(self, job: SignJob, result: SignResult) -> bool:
        """Применяет готовую подпись к записи или журналу; False — задачу уже обработали."""
        await self.session.refresh(job, with_for_update=True)
        if job.status is not SignJobStatus.PENDING:
            return False
        if job.target is SignTarget.JOURNAL:
            if self.journal_finisher is None:
                raise ConflictError("Не настроено завершение подписи журнала", code="no_finisher")
            await self.journal_finisher.finish_signing(job, result)
        else:
            await self._complete_record(job, result)
        job.status = SignJobStatus.SIGNED
        job.completed_at = datetime.now(timezone.utc)
        await append_audit(
            self.session,
            None,
            action="record.sign" if job.target is SignTarget.RECORD else "ejournal.sign",
            entity_type=job.journal_kind.value if job.target is SignTarget.RECORD else "ejournal",
            entity_id=str(job.subject_id),
            payload={
                "job": job.external_id,
                "requested_by": str(job.requested_by),
                "cert_serial": result.certificate.serial if result.certificate else None,
            },
        )
        await self.session.commit()
        return True

    async def _complete_record(self, job: SignJob, result: SignResult) -> None:
        """Сохраняет подпись записи, формирует PDF и переводит запись в статус Б."""
        kind = job.journal_kind
        record = await load_record(self.session, kind, job.subject_id, for_update=True)
        if record is None:
            raise NotFoundError("Запись удалена до завершения подписи")
        if record.status is not RecordStatus.UNSIGNED:
            raise ConflictError("Запись уже подписана", code="already_signed")
        xml = build_record_xml(kind, record)
        if _sha(xml) != job.content_sha256:
            raise ConflictError(
                "Запись изменилась после отправки на подпись", code="record_changed"
            )
        cert = result.certificate
        doc = RecordDocument(
            record_kind=kind,
            record_id=record.id,
            signer_user_id=job.signer_user_id,
            cert_serial=cert.serial if cert else None,
            cert_subject=cert.subject if cert else None,
            cert_valid_from=cert.valid_from if cert else None,
            cert_valid_to=cert.valid_to if cert else None,
            ocsp_status=result.ocsp_status,
            signed_at=result.signed_at,
        )
        pdf = await render_single_record_pdf(kind, record, doc)
        base = f"records/{kind.value}/{record.id}"
        doc.xml_key = job.content_key
        doc.pdf_key = await self.storage.put(f"{base}/record.pdf", pdf)
        doc.sig_key = await self.storage.put(f"{base}/record.xml.sig", result.signature)
        if result.tsp:
            doc.tsp_key = await self.storage.put(f"{base}/record.xml.tsp", result.tsp)
        doc.xml_sha256 = job.content_sha256
        doc.pdf_sha256 = _sha(pdf)
        self.session.add(doc)
        record.status = RecordStatus.SIGNED
        record.record_hash = job.content_sha256
        await self.session.flush()

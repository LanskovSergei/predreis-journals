"""Подпись записей личным сертификатом специалиста (электронный документ типа 1)."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.core.security import Principal
from app.core.storage import Storage, get_storage
from app.domain import fsm
from app.domain.enums import JournalKind, RecordStatus, SignatureKind
from app.domain.permissions import RECORD_PERMS, has_permission
from app.integrations.predreis.client import Signer
from app.models.documents import RecordDocument
from app.modules.audit.service import append_audit
from app.modules.records.queries import load_record
from app.modules.records.schemas import SignBatchResult, SignOutcome
from app.modules.reports.service import render_single_record_pdf
from app.modules.signing.xml_builder import build_record_xml

logger = logging.getLogger(__name__)


class SigningService:
    """Подпись записей: A → Б. Криптография выполняется в Предрейсе (ключи и лицензии там)."""

    def __init__(
        self, session: AsyncSession, signer: Signer, storage: Storage | None = None
    ) -> None:
        """Принимает сессию, подписанта (Предрейс) и хранилище файлов."""
        self.session = session
        self.signer = signer
        self.storage = storage or get_storage()

    async def sign_records(
        self, principal: Principal, kind: JournalKind, record_ids: list[uuid.UUID]
    ) -> SignBatchResult:
        """Подписывает записи по одной: сбой одной не отменяет остальные."""
        perms = RECORD_PERMS[kind]
        if not has_permission(principal.role, perms.sign):
            raise ForbiddenError("Недостаточно прав", code="permission_denied")
        limit = get_settings().mass_sign_max_batch
        if len(record_ids) > limit:
            raise AppError(f"За один запрос можно подписать не более {limit} записей")
        results: list[SignOutcome] = []
        for record_id in dict.fromkeys(record_ids):
            try:
                await self._sign_one(principal, kind, record_id)
                await self.session.commit()
            except (AppError, OSError) as exc:
                await self.session.rollback()
                code = exc.code if isinstance(exc, AppError) else "storage_error"
                logger.info("Подпись записи %s не выполнена: %s", record_id, exc)
                results.append(
                    SignOutcome(record_id=record_id, ok=False, code=code, message=str(exc))
                )
            else:
                results.append(SignOutcome(record_id=record_id, ok=True))
        signed = sum(1 for r in results if r.ok)
        return SignBatchResult(signed=signed, failed=len(results) - signed, results=results)

    async def _sign_one(
        self, principal: Principal, kind: JournalKind, record_id: uuid.UUID
    ) -> None:
        """Подписывает одну запись; аудит добавляется последним (порядок блокировок)."""
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
        xml = build_record_xml(kind, record)
        result = await self.signer.sign_detached(
            content=xml,
            filename=f"{record.id}.xml",
            kind=SignatureKind.PERSONAL,
            signer_user_id=principal.user_id,
            on_behalf_token=principal.raw_token,
        )
        doc = RecordDocument(
            record_kind=kind,
            record_id=record.id,
            signer_user_id=principal.user_id,
            cert_serial=result.cert_serial,
            cert_subject=result.cert_subject,
            cert_valid_from=result.cert_valid_from,
            cert_valid_to=result.cert_valid_to,
            ocsp_status=result.ocsp_status,
            signed_at=result.signed_at,
        )
        pdf = await render_single_record_pdf(kind, record, doc)
        base = f"records/{kind.value}/{record.id}"
        doc.xml_key = await self.storage.put(f"{base}/record.xml", xml)
        doc.pdf_key = await self.storage.put(f"{base}/record.pdf", pdf)
        doc.sig_key = await self.storage.put(f"{base}/record.xml.sig", result.signature)
        if result.tsp:
            doc.tsp_key = await self.storage.put(f"{base}/record.xml.tsp", result.tsp)
        doc.xml_sha256 = hashlib.sha256(xml).hexdigest()
        doc.pdf_sha256 = hashlib.sha256(pdf).hexdigest()
        self.session.add(doc)
        record.status = RecordStatus.SIGNED
        record.record_hash = doc.xml_sha256
        await self.session.flush()
        await append_audit(
            self.session,
            principal,
            action="record.sign",
            entity_type=kind.value,
            entity_id=str(record.id),
            payload={"cert_serial": result.cert_serial, "signed_at": _iso(result.signed_at)},
        )


def _iso(value: datetime) -> str:
    """ISO-строка момента подписи в UTC."""
    return value.astimezone(timezone.utc).isoformat()

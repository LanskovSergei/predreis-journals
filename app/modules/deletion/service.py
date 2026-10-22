"""Удаление подписанных записей: запросы (Предрейс), подтверждение и прямое удаление (Админ/СА)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.security import Principal
from app.core.storage import Storage, get_storage
from app.domain import fsm
from app.domain.enums import DeletionStatus, JournalKind
from app.domain.permissions import RECORD_PERMS, has_permission
from app.models.documents import DeletionRequest, RecordDocument
from app.models.records import AnyRecord
from app.modules.audit.service import append_audit
from app.modules.integration import outbox
from app.modules.records.queries import load_record

logger = logging.getLogger(__name__)


class DeletionService:
    """Обработка удаления записей типа Б."""

    def __init__(self, session: AsyncSession, storage: Storage | None = None) -> None:
        """Сохраняет сессию и хранилище файлов."""
        self.session = session
        self.storage = storage or get_storage()

    @staticmethod
    def _require_resolver(principal: Principal, kind: JournalKind) -> None:
        """Подтверждать/удалять подписанные записи могут Админ и СА."""
        if not has_permission(principal.role, RECORD_PERMS[kind].delete_signed):
            raise ForbiddenError("Недостаточно прав", code="permission_denied")

    async def list_requests(
        self, principal: Principal, status: DeletionStatus = DeletionStatus.PENDING
    ) -> list[DeletionRequest]:
        """Возвращает запросы на удаление (только для Админ/СА)."""
        self._require_resolver(principal, JournalKind.MEDICAL)
        rows = await self.session.execute(
            select(DeletionRequest)
            .where(DeletionRequest.status == status)
            .order_by(DeletionRequest.created_at.desc())
        )
        return list(rows.scalars().all())

    async def _purge(self, kind: JournalKind, record: AnyRecord) -> list[str]:
        """Удаляет запись и документы из БД, возвращает ключи файлов для удаления после коммита."""
        docs = (
            (
                await self.session.execute(
                    select(RecordDocument).where(
                        RecordDocument.record_kind == kind, RecordDocument.record_id == record.id
                    )
                )
            )
            .scalars()
            .all()
        )
        keys = [k for d in docs for k in (d.xml_key, d.pdf_key, d.sig_key, d.tsp_key) if k]
        await self.session.execute(
            delete(RecordDocument).where(
                RecordDocument.record_kind == kind, RecordDocument.record_id == record.id
            )
        )
        await self.session.delete(record)
        await self.session.flush()
        return keys

    async def _delete_files(self, keys: list[str]) -> None:
        """Удаляет файлы после успешного коммита (сбой хранилища не откатывает удаление)."""
        for key in keys:
            try:
                await self.storage.delete(key)
            except OSError as exc:
                logger.warning("Не удалось удалить файл %s: %s", key, exc)

    async def approve(
        self, principal: Principal, request_id: uuid.UUID, comment: str | None
    ) -> DeletionRequest:
        """Подтверждает запрос: запись и её документы удаляются."""
        request = await self._get_pending(request_id)
        self._require_resolver(principal, request.record_kind)
        record = await load_record(
            self.session, request.record_kind, request.record_id, for_update=True
        )
        if record is None:
            raise NotFoundError("Запись уже удалена")
        fsm.ensure_signed_deletable(
            status=record.status,
            source=record.source,
            reserved_journal_id=record.reserved_journal_id,
        )
        keys = await self._purge(request.record_kind, record)
        self._resolve(request, DeletionStatus.APPROVED, principal, comment)
        await append_audit(
            self.session,
            principal,
            action="record.delete_signed",
            entity_type=request.record_kind.value,
            entity_id=str(request.record_id),
            payload={"request_id": str(request.id)},
        )
        await self.session.commit()
        await self._delete_files(keys)
        return request

    async def reject(
        self, principal: Principal, request_id: uuid.UUID, comment: str | None
    ) -> DeletionRequest:
        """Отклоняет запрос: запись снова доступна в обычном состоянии."""
        request = await self._get_pending(request_id)
        self._require_resolver(principal, request.record_kind)
        record = await load_record(
            self.session, request.record_kind, request.record_id, for_update=True
        )
        if record is not None:
            record.deletion_pending = False
        self._resolve(request, DeletionStatus.REJECTED, principal, comment)
        await append_audit(
            self.session,
            principal,
            action="record.deletion_rejected",
            entity_type=request.record_kind.value,
            entity_id=str(request.record_id),
            payload={"request_id": str(request.id)},
        )
        await outbox.enqueue(
            self.session,
            "deletion.resolved",
            {"request_id": str(request.id), "status": "rejected"},
        )
        await self.session.commit()
        return request

    async def delete_signed_direct(
        self, principal: Principal, kind: JournalKind, record_id: uuid.UUID
    ) -> None:
        """Прямое удаление подписанной записи Админом/СА (без запроса)."""
        self._require_resolver(principal, kind)
        record = await load_record(self.session, kind, record_id, for_update=True)
        if record is None:
            raise NotFoundError("Запись не найдена")
        fsm.ensure_signed_deletable(
            status=record.status,
            source=record.source,
            reserved_journal_id=record.reserved_journal_id,
        )
        # Запись, поставленная на удаление, закрывается как подтверждённая.
        pending = (
            await self.session.execute(
                select(DeletionRequest).where(
                    DeletionRequest.record_kind == kind,
                    DeletionRequest.record_id == record_id,
                    DeletionRequest.status == DeletionStatus.PENDING,
                )
            )
        ).scalar_one_or_none()
        if pending is not None:
            self._resolve(pending, DeletionStatus.APPROVED, principal, "Удалено напрямую")
        keys = await self._purge(kind, record)
        await append_audit(
            self.session,
            principal,
            action="record.delete_signed",
            entity_type=kind.value,
            entity_id=str(record_id),
            payload={"direct": True},
        )
        await self.session.commit()
        await self._delete_files(keys)

    async def _get_pending(self, request_id: uuid.UUID) -> DeletionRequest:
        """Возвращает запрос в статусе pending (с блокировкой) или бросает ошибку."""
        request = (
            await self.session.execute(
                select(DeletionRequest).where(DeletionRequest.id == request_id).with_for_update()
            )
        ).scalar_one_or_none()
        if request is None:
            raise NotFoundError("Запрос не найден")
        if request.status is not DeletionStatus.PENDING:
            raise ConflictError("Запрос уже обработан", code="already_resolved")
        return request

    @staticmethod
    def _resolve(
        request: DeletionRequest,
        status: DeletionStatus,
        principal: Principal,
        comment: str | None,
    ) -> None:
        """Фиксирует решение по запросу."""
        request.status = status
        request.resolved_by = principal.user_id
        request.resolved_at = datetime.now(timezone.utc)
        request.resolution_comment = comment

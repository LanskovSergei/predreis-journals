"""Электронные журналы: DRAFT → AWAITING_SIGNATURE → SIGNED | REJECTED (ТЗ, стр. 14, 17)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationFailedError
from app.core.security import Principal
from app.domain.enums import EJournalStatus, JournalKind, RecordStatus
from app.domain.permissions import RECORD_PERMS, Permission, has_permission
from app.integrations.predreis.client import Signer
from app.models.catalog import Organization
from app.models.documents import EJournal, EJournalItem
from app.models.records import AnyRecord, record_model
from app.modules.audit.service import append_audit
from app.modules.ejournal.builder import ContainerBuilder
from app.modules.ejournal.schemas import EJournalCreate
from app.modules.integration import outbox


def _eligible(model: Any, organization_id: uuid.UUID, start: date, end: date) -> list[Any]:
    """Условия отбора записей для журнала: подписанные, не в журнале, не на удалении."""
    local_date = func.date(func.timezone(get_settings().business_timezone, model.performed_at))
    return [
        model.organization_id == organization_id,
        model.status == RecordStatus.SIGNED,
        model.deletion_pending.is_(False),
        model.reserved_journal_id.is_(None),
        local_date >= start,
        local_date <= end,
    ]


class EJournalService:
    """Жизненный цикл электронного журнала."""

    def __init__(
        self,
        session: AsyncSession,
        signer: Signer,
        builder: ContainerBuilder | None = None,
    ) -> None:
        """Принимает сессию, подписанта и строителя контейнера."""
        self.session = session
        self.signer = signer
        self.builder = builder or ContainerBuilder()

    @staticmethod
    def _require_view(principal: Principal) -> None:
        """Просмотр журналов — менеджеры, Админ, СА."""
        if not has_permission(principal.role, Permission.EJOURNAL_VIEW):
            raise ForbiddenError("Недостаточно прав", code="permission_denied")

    @staticmethod
    def _require(principal: Principal, kind: JournalKind, build: bool) -> None:
        """Проверяет право формирования (build=True) или подписи журнала данного вида."""
        perms = RECORD_PERMS[kind]
        needed = perms.ejournal_build if build else perms.ejournal_sign
        if not has_permission(principal.role, needed):
            raise ForbiddenError("Недостаточно прав", code="permission_denied")

    async def _get(self, journal_id: uuid.UUID, *, for_update: bool = False) -> EJournal:
        """Возвращает журнал или 404."""
        stmt = select(EJournal).where(EJournal.id == journal_id)
        if for_update:
            stmt = stmt.with_for_update()
        journal = (await self.session.execute(stmt)).scalar_one_or_none()
        if journal is None:
            raise NotFoundError("Электронный журнал не найден")
        return journal

    async def get(self, principal: Principal, journal_id: uuid.UUID) -> EJournal:
        """Возвращает журнал (просмотр)."""
        self._require_view(principal)
        return await self._get(journal_id)

    async def list_journals(
        self, principal: Principal, status: EJournalStatus | None, kind: JournalKind | None
    ) -> list[EJournal]:
        """Список журналов: СА видит ожидающие подписи, менеджеры — все."""
        self._require_view(principal)
        stmt = select(EJournal).order_by(EJournal.created_at.desc())
        if status:
            stmt = stmt.where(EJournal.status == status)
        if kind:
            stmt = stmt.where(EJournal.kind == kind)
        return list((await self.session.execute(stmt)).scalars().all())

    async def create(self, principal: Principal, data: EJournalCreate) -> EJournal:
        """Создаёт черновик журнала (шаг «Сформировать»). Записи ещё не резервируются."""
        self._require(principal, data.kind, build=True)
        if await self.session.get(Organization, data.organization_id) is None:
            raise NotFoundError("Организация не найдена")
        model = record_model(data.kind)
        count = (
            await self.session.execute(
                select(func.count())
                .select_from(model)
                .where(*_eligible(model, data.organization_id, data.period_from, data.period_to))
            )
        ).scalar_one()
        if count == 0:
            raise ValidationFailedError("Нет подписанных записей для журнала за период")
        journal = EJournal(
            kind=data.kind,
            organization_id=data.organization_id,
            period_from=data.period_from,
            period_to=data.period_to,
            status=EJournalStatus.DRAFT,
            record_count=count,
            created_by=principal.user_id,
        )
        self.session.add(journal)
        await self.session.flush()
        await append_audit(
            self.session,
            principal,
            action="ejournal.create",
            entity_type="ejournal",
            entity_id=str(journal.id),
            payload={"records": count},
        )
        await self.session.commit()
        return journal

    async def cancel(self, principal: Principal, journal_id: uuid.UUID) -> None:
        """Кнопка «Отмена»: удаляет черновик."""
        journal = await self._get(journal_id, for_update=True)
        self._require(principal, journal.kind, build=True)
        if journal.status is not EJournalStatus.DRAFT:
            raise ConflictError("Отменить можно только черновик", code="invalid_status")
        await self.session.delete(journal)
        await append_audit(
            self.session,
            principal,
            action="ejournal.cancel",
            entity_type="ejournal",
            entity_id=str(journal_id),
        )
        await self.session.commit()

    async def submit(self, principal: Principal, journal_id: uuid.UUID) -> EJournal:
        """Кнопка «Отправить»: резервирует записи, собирает пакет, отправляет на подпись СА."""
        journal = await self._get(journal_id, for_update=True)
        self._require(principal, journal.kind, build=True)
        if journal.status is not EJournalStatus.DRAFT:
            raise ConflictError("Журнал уже отправлен", code="invalid_status")
        model: Any = record_model(journal.kind)
        found = await self.session.execute(
            select(model)
            .where(
                *_eligible(model, journal.organization_id, journal.period_from, journal.period_to)
            )
            .with_for_update()
        )
        records: list[AnyRecord] = list(found.scalars().all())
        if not records:
            raise ValidationFailedError("Записи для журнала больше недоступны")
        for rec in records:
            rec.reserved_journal_id = journal.id
            self.session.add(
                EJournalItem(journal_id=journal.id, record_kind=journal.kind, record_id=rec.id)
            )
        journal.record_count = len(records)
        await self.session.flush()
        await self.builder.build_package(journal, records)
        journal.status = EJournalStatus.AWAITING_SIGNATURE
        journal.submitted_at = datetime.now(timezone.utc)
        await outbox.enqueue(
            self.session,
            "ejournal.submitted",
            {"journal_id": str(journal.id), "kind": journal.kind.value, "records": len(records)},
        )
        await append_audit(
            self.session,
            principal,
            action="ejournal.submit",
            entity_type="ejournal",
            entity_id=str(journal.id),
            payload={"records": len(records)},
        )
        await self.session.commit()
        return journal

    async def sign(self, principal: Principal, journal_id: uuid.UUID) -> EJournal:
        """Подпись СА: УКЭП организации, записи становятся типа В (неизменяемыми)."""
        journal = await self._get(journal_id, for_update=True)
        self._require(principal, journal.kind, build=False)
        if journal.status is not EJournalStatus.AWAITING_SIGNATURE:
            raise ConflictError("Журнал не ожидает подписи", code="invalid_status")
        await self.builder.finalize(journal, self.signer, principal)
        model = record_model(journal.kind)
        await self.session.execute(
            update(model)
            .where(model.reserved_journal_id == journal.id)
            .values(status=RecordStatus.IN_JOURNAL)
        )
        journal.status = EJournalStatus.SIGNED
        journal.signed_by = principal.user_id
        journal.signed_at = datetime.now(timezone.utc)
        await outbox.enqueue(self.session, "ejournal.signed", {"journal_id": str(journal.id)})
        await append_audit(
            self.session,
            principal,
            action="ejournal.sign",
            entity_type="ejournal",
            entity_id=str(journal.id),
            payload={"records": journal.record_count},
        )
        await self.session.commit()
        return journal

    async def reject(
        self, principal: Principal, journal_id: uuid.UUID, reason: str | None
    ) -> EJournal:
        """Отклонение СА: контейнер расформировывается, записи возвращаются в тип Б."""
        journal = await self._get(journal_id, for_update=True)
        self._require(principal, journal.kind, build=False)
        if journal.status is not EJournalStatus.AWAITING_SIGNATURE:
            raise ConflictError("Журнал не ожидает подписи", code="invalid_status")
        model = record_model(journal.kind)
        await self.session.execute(
            update(model)
            .where(model.reserved_journal_id == journal.id)
            .values(reserved_journal_id=None)
        )
        items = (
            await self.session.execute(
                select(EJournalItem).where(EJournalItem.journal_id == journal.id)
            )
        ).scalars()
        for item in items:
            await self.session.delete(item)
        journal.status = EJournalStatus.REJECTED
        journal.rejected_by = principal.user_id
        journal.reject_reason = reason
        await outbox.enqueue(self.session, "ejournal.rejected", {"journal_id": str(journal.id)})
        await append_audit(
            self.session,
            principal,
            action="ejournal.reject",
            entity_type="ejournal",
            entity_id=str(journal.id),
            payload={"reason": reason},
        )
        await self.session.commit()
        return journal

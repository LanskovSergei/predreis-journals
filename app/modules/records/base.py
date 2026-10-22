"""Общая логика обоих журналов: доступ, удаление, примечания, доступные действия."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any, ClassVar

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)
from app.core.security import Principal
from app.domain import fsm
from app.domain.enums import (
    JournalKind,
    RecordSource,
    RecordStatus,
    Role,
    WorkFormat,
)
from app.domain.permissions import CLIENT_ROLES, RECORD_PERMS, Permission, has_permission
from app.models.catalog import Driver, Organization, User, Vehicle
from app.models.documents import DeletionRequest, RecordDocument
from app.models.records import MedicalRecord, TechnicalRecord
from app.modules.audit.service import append_audit
from app.modules.integration import outbox
from app.modules.records.schemas import RecordFilters, SignatureInfo

logger = logging.getLogger(__name__)

AnyRecord = MedicalRecord | TechnicalRecord


def contains_pattern(value: str) -> str:
    """Готовит шаблон LIKE «содержит» с экранированием спецсимволов."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _allowed(check: Callable[..., None], **kwargs: Any) -> bool:
    """Возвращает True, если проверка из fsm проходит без исключения."""
    try:
        check(**kwargs)
    except (ConflictError, ForbiddenError):
        return False
    return True


class BaseRecordService:
    """Базовый сервис журнала. Наследники задают kind и model."""

    kind: ClassVar[JournalKind]
    model: ClassVar[type[Any]]
    specialist_role: ClassVar[Role]

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет сессию БД и набор прав журнала."""
        self.session = session
        self.perms = RECORD_PERMS[self.kind]

    # --- права и область видимости ---------------------------------------------------------
    def _require(self, principal: Principal, permission: Permission) -> None:
        """Бросает ForbiddenError, если у роли нет права."""
        if not has_permission(principal.role, permission):
            raise ForbiddenError("Недостаточно прав", code="permission_denied")

    def _ensure_view(self, principal: Principal) -> None:
        """Проверяет право просмотра архива (полного или по своей организации)."""
        if has_permission(principal.role, self.perms.view) or has_permission(
            principal.role, self.perms.view_own_org
        ):
            return
        raise ForbiddenError("Недостаточно прав", code="permission_denied")

    async def _scope(self, stmt: Select[Any], principal: Principal) -> Select[Any]:
        """Для клиента/диспетчера: только своя ЭПЛ-организация и только подписанные записи."""
        if principal.role not in CLIENT_ROLES:
            return stmt
        if principal.org_id is None:
            raise ForbiddenError("Пользователь не привязан к организации", code="no_organization")
        org = await self.session.get(Organization, principal.org_id)
        if org is None or org.work_format is not WorkFormat.EPL:
            raise ForbiddenError(
                "Электронные журналы доступны только организациям на ЭПЛ", code="not_epl_org"
            )
        return stmt.where(
            self.model.organization_id == principal.org_id,
            self.model.status != RecordStatus.UNSIGNED,
        )

    # --- загрузка справочников -------------------------------------------------------------
    async def _get_org(self, organization_id: uuid.UUID) -> Organization:
        """Возвращает организацию или 404."""
        org = await self.session.get(Organization, organization_id)
        if org is None:
            raise NotFoundError("Организация не найдена")
        return org

    async def _get_driver(self, driver_id: uuid.UUID, organization_id: uuid.UUID) -> Driver:
        """Возвращает водителя организации или бросает ошибку валидации."""
        driver = await self.session.get(Driver, driver_id)
        if driver is None or driver.organization_id != organization_id:
            raise ValidationFailedError("Водитель не найден в организации", code="driver_invalid")
        return driver

    async def _get_vehicle(self, vehicle_id: uuid.UUID, organization_id: uuid.UUID) -> Vehicle:
        """Возвращает ТС организации или бросает ошибку валидации."""
        vehicle = await self.session.get(Vehicle, vehicle_id)
        if vehicle is None or vehicle.organization_id != organization_id:
            raise ValidationFailedError("ТС не найдено в организации", code="vehicle_invalid")
        return vehicle

    async def _resolve_specialist(self, principal: Principal, requested: uuid.UUID | None) -> User:
        """Определяет специалиста записи: медик/механик — всегда он сам, менеджер — по запросу."""
        if principal.role is self.specialist_role:
            if requested not in (None, principal.user_id):
                raise ForbiddenError(
                    "Специалист создаёт и меняет записи только от своего имени",
                    code="specialist_mismatch",
                )
            specialist_id = principal.user_id
        else:
            if requested is None:
                raise ValidationFailedError(
                    "Укажите специалиста (specialist_user_id)", code="specialist_required"
                )
            specialist_id = requested
        user = await self.session.get(User, specialist_id)
        if user is None or user.role is not self.specialist_role or not user.is_active:
            raise ValidationFailedError(
                "Специалист не найден или имеет неподходящую роль", code="specialist_invalid"
            )
        return user

    # --- выборки ---------------------------------------------------------------------------
    def _apply_common_filters(self, stmt: Select[Any], f: RecordFilters) -> Select[Any]:
        """Применяет общие фильтры архива."""
        m = self.model
        local_date = func.date(func.timezone(self._tz_name(), m.performed_at))
        if f.organization_id:
            stmt = stmt.where(m.organization_id == f.organization_id)
        if f.date_from:
            stmt = stmt.where(local_date >= f.date_from)
        if f.date_to:
            stmt = stmt.where(local_date <= f.date_to)
        if f.specialist_user_id:
            stmt = stmt.where(m.specialist_user_id == f.specialist_user_id)
        if f.result:
            stmt = stmt.where(m.result == f.result)
        if f.has_note is not None:
            has_note = and_(m.note.is_not(None), func.length(func.trim(m.note)) > 0)
            stmt = stmt.where(has_note if f.has_note else ~has_note)
        if f.is_signed is not None:
            stmt = stmt.where(
                m.status != RecordStatus.UNSIGNED
                if f.is_signed
                else m.status == RecordStatus.UNSIGNED
            )
        return stmt

    @staticmethod
    def _tz_name() -> str:
        """Имя часового пояса бизнеса для SQL-выражений."""
        from app.core.config import get_settings

        return get_settings().business_timezone

    async def get(
        self, principal: Principal, record_id: uuid.UUID, *, for_update: bool = False
    ) -> AnyRecord:
        """Возвращает запись с учётом прав и области видимости."""
        self._ensure_view(principal)
        stmt = select(self.model).where(self.model.id == record_id)
        stmt = await self._scope(stmt, principal)
        if for_update:
            stmt = stmt.with_for_update()
        record = (await self.session.execute(stmt)).scalar_one_or_none()
        if record is None:
            raise NotFoundError("Запись не найдена")
        return record

    async def signatures(self, record_ids: list[uuid.UUID]) -> dict[uuid.UUID, RecordDocument]:
        """Загружает электронные документы (подписи) пачкой."""
        if not record_ids:
            return {}
        rows = await self.session.execute(
            select(RecordDocument).where(
                RecordDocument.record_kind == self.kind, RecordDocument.record_id.in_(record_ids)
            )
        )
        return {d.record_id: d for d in rows.scalars()}

    @staticmethod
    def signature_info(doc: RecordDocument | None) -> SignatureInfo | None:
        """Преобразует RecordDocument в краткие данные подписи."""
        if doc is None:
            return None
        return SignatureInfo(
            cert_serial=doc.cert_serial,
            cert_subject=doc.cert_subject,
            cert_valid_from=doc.cert_valid_from,
            cert_valid_to=doc.cert_valid_to,
            signed_at=doc.signed_at,
        )

    # --- доступные действия (подсказка для фронтенда) --------------------------------------
    def actions(self, record: AnyRecord, principal: Principal) -> list[str]:
        """Список действий, доступных пользователю над записью (кнопки в строке архива)."""
        if principal.role in CLIENT_ROLES:
            return []
        role, perms = principal.role, self.perms
        acts: list[str] = []
        editable = _allowed(fsm.ensure_editable, status=record.status, source=record.source)
        if editable and has_permission(role, perms.edit):
            acts += ["edit", "clear_note"]
        if editable and has_permission(role, perms.delete_unsigned):
            acts.append("delete")
        if has_permission(role, perms.sign) and _allowed(
            fsm.ensure_signable,
            status=record.status,
            source=record.source,
            note=record.note,
            deletion_pending=record.deletion_pending,
            specialist_id=record.specialist_user_id,
            actor_id=principal.user_id,
        ):
            acts.append("sign")
        if has_permission(role, perms.request_delete) and _allowed(
            fsm.ensure_deletion_requestable,
            status=record.status,
            source=record.source,
            deletion_pending=record.deletion_pending,
            reserved_journal_id=record.reserved_journal_id,
        ):
            acts.append("request_deletion")
        if has_permission(role, perms.delete_signed) and _allowed(
            fsm.ensure_signed_deletable,
            status=record.status,
            source=record.source,
            reserved_journal_id=record.reserved_journal_id,
        ):
            acts.append("delete_signed")
        return acts

    # --- общие операции --------------------------------------------------------------------
    async def delete_unsigned(self, principal: Principal, record_id: uuid.UUID) -> None:
        """Удаляет неподписанную запись (тип А)."""
        self._require(principal, self.perms.delete_unsigned)
        record = await self.get(principal, record_id, for_update=True)
        fsm.ensure_deletable_unsigned(record.status, record.source)
        await self.session.delete(record)
        await append_audit(
            self.session,
            principal,
            action="record.delete_unsigned",
            entity_type=self.kind.value,
            entity_id=str(record_id),
        )
        await self.session.commit()

    async def clear_note(self, principal: Principal, record_id: uuid.UUID) -> AnyRecord:
        """Очищает поле «Примечание» неподписанной записи."""
        self._require(principal, self.perms.edit)
        record = await self.get(principal, record_id, for_update=True)
        fsm.ensure_editable(record.status, record.source)
        record.note = None
        await append_audit(
            self.session,
            principal,
            action="record.clear_note",
            entity_type=self.kind.value,
            entity_id=str(record_id),
        )
        await self.session.commit()
        return record

    async def request_deletion(
        self, principal: Principal, record_id: uuid.UUID, reason: str | None
    ) -> DeletionRequest:
        """Создаёт запрос на удаление подписанной записи (тип Б); подтверждает Админ/СА."""
        self._require(principal, self.perms.request_delete)
        record = await self.get(principal, record_id, for_update=True)
        fsm.ensure_deletion_requestable(
            status=record.status,
            source=record.source,
            deletion_pending=record.deletion_pending,
            reserved_journal_id=record.reserved_journal_id,
        )
        record.deletion_pending = True
        request = DeletionRequest(
            record_kind=self.kind,
            record_id=record.id,
            requested_by=principal.user_id,
            reason=reason,
        )
        self.session.add(request)
        await self.session.flush()
        await outbox.enqueue(
            self.session,
            "deletion.requested",
            {"request_id": str(request.id), "kind": self.kind.value, "record_id": str(record.id)},
        )
        await append_audit(
            self.session,
            principal,
            action="record.request_deletion",
            entity_type=self.kind.value,
            entity_id=str(record_id),
            payload={"request_id": str(request.id), "reason": reason},
        )
        await self.session.commit()
        return request


__all__ = ["AnyRecord", "AppError", "BaseRecordService", "RecordSource", "contains_pattern"]

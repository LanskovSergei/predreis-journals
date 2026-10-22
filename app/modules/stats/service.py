"""Плашки статистики стартовой страницы (ТЗ, стр. 11-13)."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError
from app.core.security import Principal
from app.domain.enums import RecordStatus, Role
from app.domain.permissions import Permission, has_permission
from app.models.catalog import Driver, Organization
from app.models.records import MedicalRecord, TechnicalRecord


class RecordCounters(BaseModel):
    """Счётчики записей: на подпись / подписанных / всего."""

    to_sign: int
    signed: int
    total: int


class CountPair(BaseModel):
    """Счётчик «активно / всего»."""

    active: int
    total: int


class StatsOut(BaseModel):
    """Статистика для роли. Для медика и механика показывается только их журнал."""

    organizations: CountPair | None = None
    drivers: CountPair | None = None
    medical: RecordCounters | None = None
    technical: RecordCounters | None = None


class StatsService:
    """Подсчёт статистики."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет сессию БД."""
        self.session = session

    async def _counters(self, model: Any, specialist_id: Any | None) -> RecordCounters:
        """Считает записи по статусам, при необходимости — только данного специалиста."""
        stmt = select(model.status, func.count()).group_by(model.status)
        if specialist_id is not None:
            stmt = stmt.where(model.specialist_user_id == specialist_id)
        by_status = {row[0]: row[1] for row in (await self.session.execute(stmt)).all()}
        to_sign = by_status.get(RecordStatus.UNSIGNED, 0)
        signed = by_status.get(RecordStatus.SIGNED, 0) + by_status.get(RecordStatus.IN_JOURNAL, 0)
        return RecordCounters(to_sign=to_sign, signed=signed, total=to_sign + signed)

    async def overview(self, principal: Principal) -> StatsOut:
        """Возвращает статистику, соответствующую роли пользователя."""
        if not has_permission(principal.role, Permission.STATS_VIEW):
            raise ForbiddenError("Недостаточно прав", code="permission_denied")
        if principal.role is Role.MEDIC:
            return StatsOut(medical=await self._counters(MedicalRecord, principal.user_id))
        if principal.role is Role.MECHANIC:
            return StatsOut(technical=await self._counters(TechnicalRecord, principal.user_id))
        today = date.today()
        active_org = and_(
            Organization.is_active.is_(True),
            or_(Organization.contract_until.is_(None), Organization.contract_until >= today),
        )
        orgs_total = (await self.session.execute(select(func.count(Organization.id)))).scalar_one()
        orgs_active = (
            await self.session.execute(select(func.count(Organization.id)).where(active_org))
        ).scalar_one()
        drivers_total = (await self.session.execute(select(func.count(Driver.id)))).scalar_one()
        drivers_active = (
            await self.session.execute(
                select(func.count(Driver.id))
                .join(Organization, Organization.id == Driver.organization_id)
                .where(Driver.is_active.is_(True), active_org)
            )
        ).scalar_one()
        return StatsOut(
            organizations=CountPair(active=orgs_active, total=orgs_total),
            drivers=CountPair(active=drivers_active, total=drivers_total),
            medical=await self._counters(MedicalRecord, None),
            technical=await self._counters(TechnicalRecord, None),
        )

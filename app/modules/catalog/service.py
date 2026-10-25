"""Каталог: реплики справочников Предрейса (синхронизация и чтение)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError
from app.core.security import Principal
from app.core.sqlutil import contains_pattern
from app.domain.enums import Role
from app.domain.permissions import Permission, has_permission
from app.integrations.predreis.schemas import (
    DriverPayload,
    OrganizationPayload,
    UserPayload,
    VehiclePayload,
)
from app.models.base import Base
from app.models.catalog import Driver, Organization, User, Vehicle
from app.modules.records.schemas import Page, PageParams


async def upsert_row(session: AsyncSession, model: type[Base], values: dict[str, Any]) -> None:
    """Вставляет или обновляет строку реплики; поля, которых нет во входных данных, не трогает."""
    values = {k: v for k, v in values.items() if k != "updated_at"}
    values["synced_at"] = datetime.now(timezone.utc)
    stmt = pg_insert(model).values(**values)
    update = {k: stmt.excluded[k] for k in values if k != "id"}
    await session.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=update))


async def upsert_organization(session: AsyncSession, p: OrganizationPayload) -> None:
    """Обновляет реплику организации."""
    await upsert_row(session, Organization, p.model_dump(exclude_unset=True))


async def upsert_driver(session: AsyncSession, p: DriverPayload) -> None:
    """Обновляет реплику водителя."""
    await upsert_row(session, Driver, p.model_dump(exclude_unset=True))


async def upsert_vehicle(session: AsyncSession, p: VehiclePayload) -> None:
    """Обновляет реплику ТС."""
    await upsert_row(session, Vehicle, p.model_dump(exclude_unset=True))


async def upsert_user(session: AsyncSession, p: UserPayload) -> None:
    """Обновляет реплику пользователя; `journals_access` меняется только если передан явно."""
    await upsert_row(session, User, p.model_dump(exclude_unset=True))


async def upsert_specialist(
    session: AsyncSession, user_id: uuid.UUID, role: Role, full_name: str
) -> None:
    """Регистрирует специалиста из события; у существующего обновляется только ФИО."""
    stmt = pg_insert(User).values(id=user_id, role=role, full_name=full_name)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={"full_name": stmt.excluded.full_name, "synced_at": datetime.now(timezone.utc)},
        )
    )


async def ensure_principal_user(session: AsyncSession, principal: Principal) -> None:
    """Регистрирует вошедшего специалиста в реплике (его нет в справочниках Предрейса)."""
    await upsert_user(
        session,
        UserPayload(
            id=principal.user_id,
            role=principal.role,
            full_name=principal.full_name or str(principal.user_id),
            journals_access=principal.journals_access,
        ),
    )


class CatalogService:
    """Чтение реплик каталога (создаются и меняются только в Предрейсе)."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет сессию БД."""
        self.session = session

    @staticmethod
    def _require(principal: Principal, permission: Permission) -> None:
        """Проверяет право доступа к каталогу."""
        if not has_permission(principal.role, permission):
            raise ForbiddenError("Недостаточно прав", code="permission_denied")

    async def _page(
        self, stmt: Select[Any], params: PageParams, order: Any
    ) -> tuple[list[Any], int]:
        """Выполняет постраничную выборку и считает общее число строк."""
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(*order).offset(params.offset).limit(params.page_size)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def list_organizations(
        self, principal: Principal, params: PageParams, q: str | None, only_active: bool | None
    ) -> Page[Organization]:
        """Каталог организаций: сортировка по наименованию, поиск по названию/ИНН."""
        self._require(principal, Permission.CATALOG_VIEW)
        stmt = select(Organization)
        if q:
            pattern = contains_pattern(q)
            stmt = stmt.where(
                Organization.name.ilike(pattern, escape="\\")
                | Organization.inn.like(pattern, escape="\\")
            )
        if only_active is not None:
            stmt = stmt.where(Organization.is_active == only_active)
        rows, total = await self._page(stmt, params, [func.lower(Organization.name)])
        return Page(items=rows, total=total, page=params.page, page_size=params.page_size)

    async def list_drivers(
        self,
        principal: Principal,
        params: PageParams,
        organization_id: uuid.UUID | None,
        q: str | None,
    ) -> Page[Driver]:
        """Водители: фильтр по организации и поиск по ФИО."""
        self._require(principal, Permission.CATALOG_VIEW)
        stmt = select(Driver)
        if organization_id:
            stmt = stmt.where(Driver.organization_id == organization_id)
        if q:
            stmt = stmt.where(Driver.full_name.ilike(contains_pattern(q), escape="\\"))
        rows, total = await self._page(stmt, params, [func.lower(Driver.full_name)])
        return Page(items=rows, total=total, page=params.page, page_size=params.page_size)

    async def list_vehicles(
        self,
        principal: Principal,
        params: PageParams,
        organization_id: uuid.UUID | None,
        q: str | None,
    ) -> Page[Vehicle]:
        """ТС: фильтр по организации и поиск по госномеру."""
        self._require(principal, Permission.CATALOG_VIEW)
        stmt = select(Vehicle)
        if organization_id:
            stmt = stmt.where(Vehicle.organization_id == organization_id)
        if q:
            stmt = stmt.where(Vehicle.plate.ilike(contains_pattern(q), escape="\\"))
        rows, total = await self._page(stmt, params, [Vehicle.plate])
        return Page(items=rows, total=total, page=params.page, page_size=params.page_size)

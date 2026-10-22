"""Каталог: реплики справочников Предрейса (upsert из событий, чтение, write-through)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError
from app.core.security import Principal
from app.domain.permissions import Permission, has_permission
from app.integrations.predreis.client import PredreisClient
from app.integrations.predreis.schemas import (
    DriverPayload,
    OrganizationPayload,
    UserPayload,
    VehiclePayload,
)
from app.models.base import Base
from app.models.catalog import Driver, Organization, User, Vehicle
from app.modules.audit.service import append_audit
from app.modules.records.base import contains_pattern
from app.modules.records.schemas import Page, PageParams


async def upsert_row(session: AsyncSession, model: type[Base], values: dict[str, Any]) -> None:
    """Вставляет или обновляет строку реплики по первичному ключу (идентификатор Предрейса)."""
    values = {**values, "synced_at": datetime.now(timezone.utc)}
    stmt = pg_insert(model).values(**values)
    update = {k: stmt.excluded[k] for k in values if k != "id"}
    await session.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=update))


async def upsert_organization(session: AsyncSession, p: OrganizationPayload) -> None:
    """Обновляет реплику организации."""
    await upsert_row(session, Organization, p.model_dump())


async def upsert_driver(session: AsyncSession, p: DriverPayload) -> None:
    """Обновляет реплику водителя."""
    await upsert_row(session, Driver, p.model_dump())


async def upsert_vehicle(session: AsyncSession, p: VehiclePayload) -> None:
    """Обновляет реплику ТС."""
    await upsert_row(session, Vehicle, p.model_dump())


async def upsert_user(session: AsyncSession, p: UserPayload) -> None:
    """Обновляет реплику пользователя."""
    await upsert_row(session, User, p.model_dump())


class CatalogService:
    """Чтение каталога и создание сущностей через Предрейс (источник истины)."""

    def __init__(self, session: AsyncSession, predreis: PredreisClient) -> None:
        """Сохраняет сессию и клиент Предрейса."""
        self.session = session
        self.predreis = predreis

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

    async def _create(
        self,
        principal: Principal,
        entity: str,
        body: BaseModel,
        payload_cls: type[BaseModel],
        model: type[Base],
    ) -> Any:
        """Создаёт сущность в Предрейсе и сразу обновляет локальную реплику."""
        self._require(principal, Permission.CATALOG_MANAGE)
        created = await self.predreis.create_entity(entity, body.model_dump(mode="json"))
        payload = payload_cls.model_validate(created)
        await upsert_row(self.session, model, payload.model_dump())
        await append_audit(
            self.session,
            principal,
            action=f"catalog.create_{entity}",
            entity_type=entity,
            entity_id=str(payload.id),  # type: ignore[attr-defined]
        )
        await self.session.commit()
        return await self.session.get(model, payload.id)  # type: ignore[attr-defined]

    async def create_organization(self, principal: Principal, body: BaseModel) -> Organization:
        """Добавляет организацию (парсинг по ИНН выполняет Предрейс)."""
        return await self._create(
            principal, "organizations", body, OrganizationPayload, Organization
        )

    async def create_driver(self, principal: Principal, body: BaseModel) -> Driver:
        """Добавляет водителя."""
        return await self._create(principal, "drivers", body, DriverPayload, Driver)

    async def create_vehicle(self, principal: Principal, body: BaseModel) -> Vehicle:
        """Добавляет ТС."""
        return await self._create(principal, "vehicles", body, VehiclePayload, Vehicle)

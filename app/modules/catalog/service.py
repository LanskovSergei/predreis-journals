"""Каталог: реплики справочников Предрейса (синхронизация и чтение)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationFailedError
from app.core.security import Principal
from app.core.sqlutil import contains_pattern
from app.domain.enums import CatalogOrigin, Role, WorkFormat
from app.domain.permissions import Permission, has_permission
from app.domain.validators import normalize_plate
from app.integrations.predreis.schemas import (
    DriverPayload,
    OrganizationPayload,
    UserPayload,
    VehiclePayload,
)
from app.models.base import Base
from app.models.catalog import Driver, Organization, User, Vehicle
from app.models.records import MedicalRecord, TechnicalRecord
from app.modules.audit.service import append_audit
from app.modules.catalog.schemas import (
    DriversCreate,
    DriverUpdate,
    OrganizationCreate,
    OrganizationUpdate,
    VehiclesCreate,
    VehicleUpdate,
)
from app.modules.records.schemas import Page, PageParams


async def upsert_row(session: AsyncSession, model: type[Base], values: dict[str, Any]) -> None:
    """Вставляет или обновляет строку реплики; поля, которых нет во входных данных, не трогает."""
    values = {k: v for k, v in values.items() if k != "updated_at"}
    values["synced_at"] = datetime.now(timezone.utc)
    stmt = pg_insert(model).values(**values)
    update = {k: stmt.excluded[k] for k in values if k != "id"}
    await session.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=update))


class MissingReferenceError(Exception):
    """Строка ссылается на организацию, которой ещё нет (синхронизация повторит позже)."""


async def _by_predreis_id(session: AsyncSession, model: Any, predreis_id: uuid.UUID) -> Any:
    """Карточка по идентификатору Предрейса."""
    return (
        await session.execute(select(model).where(model.predreis_id == predreis_id))
    ).scalar_one_or_none()


def _single(rows: Sequence[Any]) -> Any:
    """Единственный кандидат на объединение; при нескольких не угадываем."""
    return rows[0] if len(rows) == 1 else None


async def _link(session: AsyncSession, row: Any, predreis_id: uuid.UUID, entity: str) -> None:
    """Объединяет карточку, добавленную вручную, с карточкой платформы (наш id сохраняется)."""
    row.predreis_id = predreis_id
    row.origin = CatalogOrigin.PLATFORM
    await append_audit(
        session,
        None,
        action="catalog.linked",
        entity_type=entity,
        entity_id=str(row.id),
        payload={"predreis_id": str(predreis_id)},
    )


def _platform_values(payload: Any) -> tuple[uuid.UUID, dict[str, Any]]:
    """Идентификатор Предрейса и поля, которые приходят из платформы."""
    values = payload.model_dump(exclude_unset=True)
    values.pop("updated_at", None)
    return values.pop("id"), values


def _new(model: Any, predreis_id: uuid.UUID, values: dict[str, Any]) -> Any:
    """Новая карточка платформы: наш id совпадает с идентификатором Предрейса."""
    return model(id=predreis_id, predreis_id=predreis_id, origin=CatalogOrigin.PLATFORM, **values)


def _apply(row: Any, values: dict[str, Any]) -> None:
    """Обновляет поля платформы; поля, которые ведут только журналы, не трогает."""
    for key, value in values.items():
        setattr(row, key, value)
    row.synced_at = datetime.now(timezone.utc)


async def upsert_organization(session: AsyncSession, p: OrganizationPayload) -> None:
    """Организация из Предрейса: по id Предрейса, иначе объединение с ручной по ИНН."""
    predreis_id, values = _platform_values(p)
    row = await _by_predreis_id(session, Organization, predreis_id)
    if row is None:
        candidates = await session.execute(
            select(Organization).where(
                Organization.origin == CatalogOrigin.MANUAL,
                Organization.predreis_id.is_(None),
                Organization.inn == p.inn,
            )
        )
        row = _single(candidates.scalars().all())
        if row is not None:
            await _link(session, row, predreis_id, "organization")
            row.work_format = WorkFormat.EPL  # теперь клиент организации работает и на платформе
    if row is None:
        session.add(_new(Organization, predreis_id, values))
        return
    _apply(row, values)


async def _our_org_id(session: AsyncSession, predreis_org_id: uuid.UUID) -> uuid.UUID:
    """Наш id организации по идентификатору Предрейса (у объединённой карточки они различаются)."""
    org = await _by_predreis_id(session, Organization, predreis_org_id)
    if org is None:
        raise MissingReferenceError(f"Организация {predreis_org_id} ещё не синхронизирована")
    return org.id


async def upsert_driver(session: AsyncSession, p: DriverPayload) -> None:
    """Водитель из Предрейса: по id Предрейса, иначе объединение с ручным по ФИО и дате."""
    predreis_id, values = _platform_values(p)
    values["organization_id"] = org_id = await _our_org_id(session, p.organization_id)
    row = await _by_predreis_id(session, Driver, predreis_id)
    if row is None:
        candidates = (
            (
                await session.execute(
                    select(Driver).where(
                        Driver.organization_id == org_id,
                        Driver.origin == CatalogOrigin.MANUAL,
                        Driver.predreis_id.is_(None),
                        func.lower(Driver.full_name) == p.full_name.lower(),
                    )
                )
            )
            .scalars()
            .all()
        )
        if (
            p.birth_date is not None
        ):  # дата рождения различает тёзок; без неё сравниваем только ФИО
            candidates = [d for d in candidates if d.birth_date in (None, p.birth_date)]
        row = _single(candidates)
        if row is not None:
            await _link(session, row, predreis_id, "driver")
    if row is None:
        session.add(_new(Driver, predreis_id, values))
        return
    _apply(row, values)


async def upsert_vehicle(session: AsyncSession, p: VehiclePayload) -> None:
    """ТС из Предрейса: по id Предрейса, иначе объединение с ручным по госномеру."""
    predreis_id, values = _platform_values(p)
    values["organization_id"] = org_id = await _our_org_id(session, p.organization_id)
    row = await _by_predreis_id(session, Vehicle, predreis_id)
    if row is None:
        candidates = (
            (
                await session.execute(
                    select(Vehicle).where(
                        Vehicle.organization_id == org_id,
                        Vehicle.origin == CatalogOrigin.MANUAL,
                        Vehicle.predreis_id.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        wanted = normalize_plate(p.plate)
        row = _single([v for v in candidates if normalize_plate(v.plate) == wanted])
        if row is not None:
            await _link(session, row, predreis_id, "vehicle")
    if row is None:
        session.add(_new(Vehicle, predreis_id, values))
        return
    _apply(row, values)


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


# Правовые формы в начале наименования (длинные раньше коротких: «пао» раньше «ао»).
LEGAL_FORMS = (
    "общество с ограниченной ответственностью|индивидуальный предприниматель|"
    "публичное акционерное общество|непубличное акционерное общество|"
    "закрытое акционерное общество|открытое акционерное общество|акционерное общество|"
    "федеральное государственное унитарное предприятие|государственное унитарное предприятие|"
    "муниципальное унитарное предприятие|автономная некоммерческая организация|"
    "ооо|ип|пао|зао|оао|ао|фгуп|гуп|муп|ано|нко"
)


def org_sort_key(name: Any) -> Any:
    """Ключ сортировки каталога: наименование без правовой формы и кавычек (ТЗ, стр. 15)."""
    without_form = func.regexp_replace(name, rf"^\s*({LEGAL_FORMS})\s+", "", "i")
    return func.lower(func.regexp_replace(without_form, r"^[\s«»\"'“”„]+", ""))


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
        self,
        principal: Principal,
        params: PageParams,
        q: str | None,
        only_active: bool | None,
        origin: CatalogOrigin | None = None,
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
        if origin is not None:
            stmt = stmt.where(Organization.origin == origin)
        rows, total = await self._page(
            stmt, params, [org_sort_key(Organization.name), func.lower(Organization.name)]
        )
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


# --- ручной каталог: бумажные клиенты, а также водители и ТС гибридных клиентов ------------------
PLATFORM_ORG_FIELDS = {
    "inn",
    "legal_form",
    "name",
    "short_name",
    "kpp",
    "ogrn",
    "legal_address",
    "is_active",
}
PLATFORM_DRIVER_FIELDS = {"full_name", "gender", "birth_date", "license_number", "is_active"}
PLATFORM_VEHICLE_FIELDS = {"brand", "model", "vehicle_type", "plate", "is_active"}


class ManualCatalogService(CatalogService):
    """Добавление и правка карточек в журналах (решение заказчика: общий каталог всех организаций).

    Карточки из платформы ПРЕДРЕЙС: реквизиты меняются только там, в журналах правятся поля,
    которые ведут только журналы (договор, контакты, СНИЛС, сроки ВУ, диагностическая карта,
    примечание). Карточки, по которым есть записи, не удаляются: их делают неактивными.
    """

    async def _get(self, model: Any, row_id: uuid.UUID) -> Any:
        """Карточка или 404."""
        row = await self.session.get(model, row_id)
        if row is None:
            raise NotFoundError("Не найдено")
        return row

    async def _audit(
        self,
        principal: Principal,
        action: str,
        entity: str,
        row_id: uuid.UUID,
        fields: list[str] | None = None,
    ) -> None:
        """Запись в журнал аудита."""
        await append_audit(
            self.session,
            principal,
            action=action,
            entity_type=entity,
            entity_id=str(row_id),
            payload={"fields": sorted(fields)} if fields else None,
        )

    @staticmethod
    def _guard_platform(row: Any, changes: dict[str, Any], platform_fields: set[str]) -> None:
        """Реквизиты карточек из платформы в журналах не меняются."""
        locked = sorted(set(changes) & platform_fields)
        if row.origin is CatalogOrigin.PLATFORM and locked:
            raise ConflictError(
                "Эти данные ведутся в ПРЕДРЕЙС: " + ", ".join(locked),
                code="managed_by_predreis",
                details={"fields": locked},
            )

    async def _records_exist(self, **where: uuid.UUID) -> bool:
        """Есть ли записи журналов, ссылающиеся на карточку."""
        for model in (MedicalRecord, TechnicalRecord):
            conditions = [getattr(model, k) == v for k, v in where.items() if hasattr(model, k)]
            if not conditions:
                continue
            found = await self.session.execute(select(model.id).where(*conditions).limit(1))
            if found.first() is not None:
                return True
        return False

    # --- организации ---
    async def create_organization(
        self, principal: Principal, data: OrganizationCreate
    ) -> Organization:
        """Добавляет организацию вручную; ИНН уникален во всём каталоге."""
        self._require(principal, Permission.CATALOG_MANAGE)
        await self._ensure_inn_free(data.inn)
        org = Organization(
            id=uuid.uuid4(),
            origin=CatalogOrigin.MANUAL,
            predreis_id=None,
            work_format=WorkFormat.PAPER,
            is_active=True,
            **data.model_dump(),
        )
        self.session.add(org)
        await self._audit(principal, "catalog.created", "organization", org.id)
        await self.session.commit()
        return org

    async def _ensure_inn_free(self, inn: str, except_id: uuid.UUID | None = None) -> None:
        """ИНН не должен повторяться: одна организация — одна карточка."""
        stmt = select(Organization.id).where(Organization.inn == inn)
        if except_id is not None:
            stmt = stmt.where(Organization.id != except_id)
        existing = (await self.session.execute(stmt.limit(1))).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(
                "Организация с таким ИНН уже есть в каталоге",
                code="organization_exists",
                details={"organization_id": str(existing)},
            )

    async def update_organization(
        self, principal: Principal, org_id: uuid.UUID, data: OrganizationUpdate
    ) -> Organization:
        """Правка карточки организации."""
        self._require(principal, Permission.CATALOG_MANAGE)
        org = await self._get(Organization, org_id)
        changes = data.model_dump(exclude_unset=True)
        self._guard_platform(org, changes, PLATFORM_ORG_FIELDS)
        if "inn" in changes:
            await self._ensure_inn_free(changes["inn"], except_id=org.id)
        for key, value in changes.items():
            setattr(org, key, value)
        await self._audit(principal, "catalog.updated", "organization", org.id, list(changes))
        await self.session.commit()
        return org

    async def delete_organization(self, principal: Principal, org_id: uuid.UUID) -> None:
        """Удаляет ручную организацию без водителей, ТС и записей; иначе — сделать неактивной."""
        self._require(principal, Permission.CATALOG_MANAGE)
        org = await self._get(Organization, org_id)
        if org.origin is CatalogOrigin.PLATFORM:
            raise ConflictError(
                "Организация из ПРЕДРЕЙС удаляется там", code="managed_by_predreis"
            )
        has_children = (
            await self.session.execute(
                select(Driver.id).where(Driver.organization_id == org.id).limit(1)
            )
        ).first() or (
            await self.session.execute(
                select(Vehicle.id).where(Vehicle.organization_id == org.id).limit(1)
            )
        ).first()
        if has_children or await self._records_exist(organization_id=org.id):
            raise ConflictError(
                "У организации есть водители, ТС или записи: сделайте её неактивной", code="in_use"
            )
        await self.session.delete(org)
        await self._audit(principal, "catalog.deleted", "organization", org_id)
        await self.session.commit()

    # --- водители ---
    async def create_drivers(self, principal: Principal, data: DriversCreate) -> list[Driver]:
        """Добавляет до 10 водителей; всё или ничего, чтобы не было половины формы."""
        self._require(principal, Permission.CATALOG_MANAGE)
        created: list[Driver] = []
        seen: set[tuple[uuid.UUID, str, Any]] = set()
        for index, item in enumerate(data.drivers):
            await self._get_active_org(item.organization_id)
            key = (item.organization_id, item.full_name.strip().lower(), item.birth_date)
            duplicate = (
                key in seen
                or (
                    await self.session.execute(
                        select(Driver.id)
                        .where(
                            Driver.organization_id == item.organization_id,
                            func.lower(Driver.full_name) == key[1],
                            Driver.birth_date.is_(None)
                            if item.birth_date is None
                            else Driver.birth_date == item.birth_date,
                        )
                        .limit(1)
                    )
                ).first()
                is not None
            )
            if duplicate:
                raise ConflictError(
                    f"Водитель №{index + 1} уже есть в организации",
                    code="driver_exists",
                    details={"index": index},
                )
            seen.add(key)
            driver = Driver(
                id=uuid.uuid4(), origin=CatalogOrigin.MANUAL, is_active=True, **item.model_dump()
            )
            driver.full_name = item.full_name.strip()
            self.session.add(driver)
            created.append(driver)
        for driver in created:
            await self._audit(principal, "catalog.created", "driver", driver.id)
        await self.session.commit()
        return created

    async def _get_active_org(self, org_id: uuid.UUID) -> Organization:
        """Организация для новой карточки: существует и активна."""
        org = await self.session.get(Organization, org_id)
        if org is None or not org.is_active:
            raise ValidationFailedError(
                "Организация не найдена или неактивна", code="organization_invalid"
            )
        return org

    async def update_driver(
        self, principal: Principal, driver_id: uuid.UUID, data: DriverUpdate
    ) -> Driver:
        """Правка водителя."""
        self._require(principal, Permission.CATALOG_MANAGE)
        driver = await self._get(Driver, driver_id)
        changes = data.model_dump(exclude_unset=True)
        self._guard_platform(driver, changes, PLATFORM_DRIVER_FIELDS)
        for key, value in changes.items():
            setattr(driver, key, value)
        await self._audit(principal, "catalog.updated", "driver", driver.id, list(changes))
        await self.session.commit()
        return driver

    async def delete_driver(self, principal: Principal, driver_id: uuid.UUID) -> None:
        """Удаляет ручного водителя без записей."""
        self._require(principal, Permission.CATALOG_MANAGE)
        driver = await self._get(Driver, driver_id)
        if driver.origin is CatalogOrigin.PLATFORM:
            raise ConflictError("Водитель из ПРЕДРЕЙС удаляется там", code="managed_by_predreis")
        if await self._records_exist(driver_id=driver.id):
            raise ConflictError("По водителю есть записи: сделайте его неактивным", code="in_use")
        await self.session.delete(driver)
        await self._audit(principal, "catalog.deleted", "driver", driver_id)
        await self.session.commit()

    # --- ТС ---
    async def create_vehicles(self, principal: Principal, data: VehiclesCreate) -> list[Vehicle]:
        """Добавляет до 10 ТС; госномер уникален в организации; всё или ничего."""
        self._require(principal, Permission.CATALOG_MANAGE)
        created: list[Vehicle] = []
        seen: set[tuple[uuid.UUID, str]] = set()
        for index, item in enumerate(data.vehicles):
            await self._get_active_org(item.organization_id)
            existing = (
                (
                    await self.session.execute(
                        select(Vehicle.plate).where(
                            Vehicle.organization_id == item.organization_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            key = (item.organization_id, item.plate)
            if key in seen or item.plate in {normalize_plate(p) for p in existing}:
                raise ConflictError(
                    f"ТС №{index + 1} с таким госномером уже есть в организации",
                    code="vehicle_exists",
                    details={"index": index},
                )
            seen.add(key)
            vehicle = Vehicle(
                id=uuid.uuid4(), origin=CatalogOrigin.MANUAL, is_active=True, **item.model_dump()
            )
            self.session.add(vehicle)
            created.append(vehicle)
        for vehicle in created:
            await self._audit(principal, "catalog.created", "vehicle", vehicle.id)
        await self.session.commit()
        return created

    async def update_vehicle(
        self, principal: Principal, vehicle_id: uuid.UUID, data: VehicleUpdate
    ) -> Vehicle:
        """Правка ТС."""
        self._require(principal, Permission.CATALOG_MANAGE)
        vehicle = await self._get(Vehicle, vehicle_id)
        changes = data.model_dump(exclude_unset=True)
        self._guard_platform(vehicle, changes, PLATFORM_VEHICLE_FIELDS)
        for key, value in changes.items():
            setattr(vehicle, key, value)
        await self._audit(principal, "catalog.updated", "vehicle", vehicle.id, list(changes))
        await self.session.commit()
        return vehicle

    async def delete_vehicle(self, principal: Principal, vehicle_id: uuid.UUID) -> None:
        """Удаляет ручное ТС без записей."""
        self._require(principal, Permission.CATALOG_MANAGE)
        vehicle = await self._get(Vehicle, vehicle_id)
        if vehicle.origin is CatalogOrigin.PLATFORM:
            raise ConflictError("ТС из ПРЕДРЕЙС удаляется там", code="managed_by_predreis")
        if await self._records_exist(vehicle_id=vehicle.id):
            raise ConflictError("По ТС есть записи: сделайте его неактивным", code="in_use")
        await self.session.delete(vehicle)
        await self._audit(principal, "catalog.deleted", "vehicle", vehicle_id)
        await self.session.commit()

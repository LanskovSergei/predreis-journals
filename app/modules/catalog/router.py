"""HTTP-эндпоинты каталога организаций, водителей и ТС."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Principal, get_principal
from app.domain.enums import CatalogOrigin
from app.modules.catalog.schemas import (
    DriverOut,
    DriversCreate,
    DriverUpdate,
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
    VehicleOut,
    VehiclesCreate,
    VehicleUpdate,
)
from app.modules.catalog.service import CatalogService, ManualCatalogService
from app.modules.records.schemas import Page, PageParams, page_params

router = APIRouter(prefix="/catalog", tags=["Каталог"])


def _service(session: AsyncSession) -> CatalogService:
    """Создаёт сервис каталога."""
    return CatalogService(session)


@router.get("/organizations", response_model=Page[OrganizationOut], summary="Каталог организаций")
async def list_organizations(
    q: str | None = None,
    only_active: bool | None = None,
    origin: CatalogOrigin | None = None,
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Page[OrganizationOut]:
    """Организации (сортировка по наименованию)."""
    page = await _service(session).list_organizations(principal, params, q, only_active, origin)
    return Page[OrganizationOut](
        items=[OrganizationOut.model_validate(o) for o in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/drivers", response_model=Page[DriverOut], summary="Водители")
async def list_drivers(
    organization_id: uuid.UUID | None = None,
    q: str | None = None,
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Page[DriverOut]:
    """Водители (поиск по ФИО)."""
    page = await _service(session).list_drivers(principal, params, organization_id, q)
    return Page[DriverOut](
        items=[DriverOut.model_validate(d) for d in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/vehicles", response_model=Page[VehicleOut], summary="Транспортные средства")
async def list_vehicles(
    organization_id: uuid.UUID | None = None,
    q: str | None = None,
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Page[VehicleOut]:
    """ТС (поиск по госномеру)."""
    page = await _service(session).list_vehicles(principal, params, organization_id, q)
    return Page[VehicleOut](
        items=[VehicleOut.model_validate(v) for v in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
    )


# --- ручной каталог (Предрейс, Админ, СА) -----------------------------------------------------
def _manual(session: AsyncSession) -> ManualCatalogService:
    """Создаёт сервис ручного каталога."""
    return ManualCatalogService(session)


@router.post(
    "/organizations",
    response_model=OrganizationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить организацию вручную",
)
async def create_organization(
    body: OrganizationCreate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> OrganizationOut:
    """Организация без платформы ПРЕДРЕЙС (бумажный клиент); ИНН уникален в каталоге."""
    return OrganizationOut.model_validate(
        await _manual(session).create_organization(principal, body)
    )


@router.patch(
    "/organizations/{org_id}", response_model=OrganizationOut, summary="Изменить организацию"
)
async def update_organization(
    org_id: uuid.UUID,
    body: OrganizationUpdate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> OrganizationOut:
    """У организаций из платформы меняются только поля журналов (договор, контакты, примечание)."""
    org = await _manual(session).update_organization(principal, org_id, body)
    return OrganizationOut.model_validate(org)


@router.delete(
    "/organizations/{org_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить организацию, добавленную вручную",
)
async def delete_organization(
    org_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Только без водителей, ТС и записей; иначе организацию делают неактивной."""
    await _manual(session).delete_organization(principal, org_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/drivers",
    response_model=list[DriverOut],
    status_code=status.HTTP_201_CREATED,
    summary="Добавить водителей вручную (до 10)",
)
async def create_drivers(
    body: DriversCreate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[DriverOut]:
    """Водители к любой организации, в т. ч. из платформы (гибридные клиенты)."""
    drivers = await _manual(session).create_drivers(principal, body)
    return [DriverOut.model_validate(d) for d in drivers]


@router.patch("/drivers/{driver_id}", response_model=DriverOut, summary="Изменить водителя")
async def update_driver(
    driver_id: uuid.UUID,
    body: DriverUpdate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> DriverOut:
    """У водителей из платформы меняются только СНИЛС, сроки ВУ и примечание."""
    return DriverOut.model_validate(
        await _manual(session).update_driver(principal, driver_id, body)
    )


@router.delete(
    "/drivers/{driver_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить водителя, добавленного вручную",
)
async def delete_driver(
    driver_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Только без записей; иначе водителя делают неактивным."""
    await _manual(session).delete_driver(principal, driver_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/vehicles",
    response_model=list[VehicleOut],
    status_code=status.HTTP_201_CREATED,
    summary="Добавить ТС вручную (до 10)",
)
async def create_vehicles(
    body: VehiclesCreate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[VehicleOut]:
    """ТС к любой организации; госномер уникален в организации."""
    vehicles = await _manual(session).create_vehicles(principal, body)
    return [VehicleOut.model_validate(v) for v in vehicles]


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleOut, summary="Изменить ТС")
async def update_vehicle(
    vehicle_id: uuid.UUID,
    body: VehicleUpdate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> VehicleOut:
    """У ТС из платформы меняются только диагностическая карта и примечание."""
    return VehicleOut.model_validate(
        await _manual(session).update_vehicle(principal, vehicle_id, body)
    )


@router.delete(
    "/vehicles/{vehicle_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить ТС, добавленное вручную",
)
async def delete_vehicle(
    vehicle_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Только без записей; иначе ТС делают неактивным."""
    await _manual(session).delete_vehicle(principal, vehicle_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

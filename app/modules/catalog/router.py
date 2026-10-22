"""HTTP-эндпоинты каталога организаций, водителей и ТС."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Principal, get_principal
from app.integrations.predreis.client import get_predreis_client
from app.modules.catalog.schemas import (
    DriverCreate,
    DriverOut,
    OrganizationCreate,
    OrganizationOut,
    VehicleCreate,
    VehicleOut,
)
from app.modules.catalog.service import CatalogService
from app.modules.records.schemas import Page, PageParams, page_params

router = APIRouter(prefix="/catalog", tags=["Каталог"])


def _service(session: AsyncSession) -> CatalogService:
    """Создаёт сервис каталога."""
    return CatalogService(session, get_predreis_client())


@router.get("/organizations", response_model=Page[OrganizationOut], summary="Каталог организаций")
async def list_organizations(
    q: str | None = None,
    only_active: bool | None = None,
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Page[OrganizationOut]:
    """Организации (сортировка по наименованию)."""
    page = await _service(session).list_organizations(principal, params, q, only_active)
    return Page[OrganizationOut](
        items=[OrganizationOut.model_validate(o) for o in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post(
    "/organizations",
    response_model=OrganizationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить организацию",
)
async def create_organization(
    body: OrganizationCreate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> OrganizationOut:
    """Создаёт организацию в Предрейсе (реквизиты по ИНН) и в реплике журналов."""
    return OrganizationOut.model_validate(
        await _service(session).create_organization(principal, body)
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


@router.post(
    "/drivers",
    response_model=DriverOut,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить водителя",
)
async def create_driver(
    body: DriverCreate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> DriverOut:
    """Создаёт водителя в Предрейсе и в реплике журналов."""
    return DriverOut.model_validate(await _service(session).create_driver(principal, body))


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


@router.post(
    "/vehicles",
    response_model=VehicleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить ТС",
)
async def create_vehicle(
    body: VehicleCreate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> VehicleOut:
    """Создаёт ТС в Предрейсе и в реплике журналов."""
    return VehicleOut.model_validate(await _service(session).create_vehicle(principal, body))

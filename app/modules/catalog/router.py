"""HTTP-эндпоинты каталога организаций, водителей и ТС."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Principal, get_principal
from app.modules.catalog.schemas import DriverOut, OrganizationOut, VehicleOut
from app.modules.catalog.service import CatalogService
from app.modules.records.schemas import Page, PageParams, page_params

router = APIRouter(prefix="/catalog", tags=["Каталог"])


def _service(session: AsyncSession) -> CatalogService:
    """Создаёт сервис каталога."""
    return CatalogService(session)


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

"""Сертификаты и специалисты: данные для стартовых страниц и фильтров архива."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Principal, get_principal
from app.domain.enums import Role
from app.integrations.predreis.client import PredreisClient, get_predreis_client
from app.modules.specialists.schemas import MyCertificatesOut, SpecialistsOut
from app.modules.specialists.service import SpecialistsService

router = APIRouter(tags=["Специалисты и сертификаты"])


@router.get(
    "/me/certificates",
    response_model=MyCertificatesOut,
    summary="Мои сертификаты (медик, механик)",
)
async def my_certificates(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    source: PredreisClient = Depends(get_predreis_client),
) -> MyCertificatesOut:
    """Сертификаты текущего специалиста со статусом и сроком действия (отзыв не проверяется)."""
    return await SpecialistsService(session, source).my_certificates(principal)


@router.get(
    "/specialists",
    response_model=SpecialistsOut,
    summary="Медики или механики с сертификатами (счётчики записей для СА)",
)
async def list_specialists(
    role: Literal["medic", "mechanic"] = "medic",
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    source: PredreisClient = Depends(get_predreis_client),
) -> SpecialistsOut:
    """Список для плашек сертификатов и фильтра «ФИО медика/механика»; менеджерские роли."""
    return await SpecialistsService(session, source).list_specialists(principal, Role(role))

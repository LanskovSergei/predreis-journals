"""HTTP-эндпоинты статистики и профиля текущего пользователя."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ForbiddenError
from app.core.security import Principal, get_principal
from app.domain.enums import Role
from app.domain.permissions import PERMISSION_ROLES, Permission, has_permission
from app.integrations.predreis.client import get_predreis_client
from app.modules.stats.service import StatsOut, StatsService

router = APIRouter(tags=["Профиль и статистика"])


@router.get("/me", summary="Текущий пользователь и его права")
async def me(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """Профиль и список прав — для построения интерфейса на фронтенде."""
    return {
        "user_id": principal.user_id,
        "role": principal.role,
        "full_name": principal.full_name,
        "organization_id": principal.org_id,
        "permissions": sorted(
            p.value for p in PERMISSION_ROLES if has_permission(principal.role, p)
        ),
    }


@router.get("/stats/overview", response_model=StatsOut, summary="Плашки статистики")
async def overview(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> StatsOut:
    """Статистика по организациям, водителям и записям."""
    return await StatsService(session).overview(principal)


@router.get("/stats/certificates", summary="Сертификаты медиков и механиков")
async def certificates(principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    """Статусы сертификатов из Предрейса; медик и механик видят только свой."""
    if not has_permission(principal.role, Permission.STATS_VIEW):
        raise ForbiddenError("Недостаточно прав", code="permission_denied")
    own = principal.user_id if principal.role in {Role.MEDIC, Role.MECHANIC} else None
    return await get_predreis_client().list_certificates(own)

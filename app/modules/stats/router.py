"""HTTP-эндпоинты статистики и профиля текущего пользователя."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Principal, get_principal
from app.domain.permissions import PERMISSION_ROLES, has_permission
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

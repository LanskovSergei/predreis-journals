"""HTTP-эндпоинты статистики и профиля текущего пользователя."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Principal, get_principal
from app.domain.contracts import journal_allowed
from app.domain.enums import CatalogOrigin, JournalKind
from app.domain.permissions import CLIENT_ROLES, PERMISSION_ROLES, has_permission
from app.models.catalog import Organization
from app.modules.records.base import RECORD_PERMS
from app.modules.stats.service import StatsOut, StatsService

router = APIRouter(tags=["Профиль и статистика"])


@router.get("/me", summary="Текущий пользователь и его права")
async def me(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Профиль, права и журналы, которые показывать (у клиента — по договору его организации)."""
    return {
        "journals": await available_journals(session, principal),
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


async def available_journals(session: AsyncSession, principal: Principal) -> list[str]:
    """Журналы, доступные пользователю: по правам роли, а у клиента ещё по договору организации."""
    kinds = [
        kind
        for kind in (JournalKind.MEDICAL, JournalKind.TECHNICAL)
        if has_permission(principal.role, RECORD_PERMS[kind].view)
        or has_permission(principal.role, RECORD_PERMS[kind].view_own_org)
    ]
    if principal.role in CLIENT_ROLES:
        org = await session.get(Organization, principal.org_id) if principal.org_id else None
        if org is None or org.origin is not CatalogOrigin.PLATFORM:
            return []
        kinds = [k for k in kinds if journal_allowed(org.contract_type, k)]
    return [k.value for k in kinds]

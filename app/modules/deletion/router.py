"""HTTP-эндпоинты удаления подписанных записей."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Principal, get_principal
from app.domain.enums import DeletionStatus, JournalKind
from app.modules.deletion.service import DeletionService
from app.modules.records.schemas import DeletionRequestOut

router = APIRouter(tags=["Удаление подписанных записей"])


class ResolutionIn(BaseModel):
    """Комментарий к решению по запросу."""

    comment: str | None = Field(default=None, max_length=1000)


@router.get(
    "/deletion-requests", response_model=list[DeletionRequestOut], summary="Запросы на удаление"
)
async def list_requests(
    status_filter: DeletionStatus = DeletionStatus.PENDING,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[DeletionRequestOut]:
    """Список запросов на удаление (Админ/СА)."""
    rows = await DeletionService(session).list_requests(principal, status_filter)
    return [DeletionRequestOut.model_validate(r) for r in rows]


@router.post(
    "/deletion-requests/{request_id}/approve",
    response_model=DeletionRequestOut,
    summary="Подтвердить удаление",
)
async def approve(
    request_id: uuid.UUID,
    body: ResolutionIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> DeletionRequestOut:
    """Подтверждает запрос: запись удаляется."""
    req = await DeletionService(session).approve(principal, request_id, body.comment)
    return DeletionRequestOut.model_validate(req)


@router.post(
    "/deletion-requests/{request_id}/reject",
    response_model=DeletionRequestOut,
    summary="Отклонить удаление",
)
async def reject(
    request_id: uuid.UUID,
    body: ResolutionIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> DeletionRequestOut:
    """Отклоняет запрос: запись остаётся."""
    req = await DeletionService(session).reject(principal, request_id, body.comment)
    return DeletionRequestOut.model_validate(req)


@router.delete(
    "/records/{kind}/{record_id}/signed",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить подписанную запись напрямую (Админ/СА)",
)
async def delete_signed(
    kind: JournalKind,
    record_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Прямое удаление записи типа Б."""
    await DeletionService(session).delete_signed_direct(principal, kind, record_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

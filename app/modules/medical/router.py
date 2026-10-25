"""HTTP-эндпоинты журнала медицинских осмотров."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Principal, get_principal
from app.domain.enums import JournalKind
from app.integrations.predreis.client import get_predreis_client
from app.modules.medical.schemas import MedicalRecordCreate, MedicalRecordUpdate
from app.modules.medical.service import MedicalOut, MedicalService
from app.modules.records.schemas import (
    DeletionRequestIn,
    DeletionRequestOut,
    MedicalFilters,
    Page,
    PageParams,
    SignBatchResult,
    SignRequest,
    page_params,
)
from app.modules.signing.service import SigningService

router = APIRouter(prefix="/medical/records", tags=["Журнал медосмотров"])


@router.get("", response_model=Page[MedicalOut], summary="Архив записей медосмотров")
async def list_records(
    filters: Annotated[MedicalFilters, Query()],
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Page[MedicalOut]:
    """Возвращает страницу архива с фильтрами."""
    return await MedicalService(session).list_records(principal, filters, params)


@router.post(
    "", response_model=MedicalOut, status_code=status.HTTP_201_CREATED, summary="Создать запись"
)
async def create_record(
    body: MedicalRecordCreate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> MedicalOut:
    """Создаёт неподписанную запись медосмотра."""
    return await MedicalService(session).create(principal, body)


@router.post(
    "/sign", response_model=SignBatchResult, summary="Отправить записи на подпись (в т.ч. массово)"
)
async def sign_records(
    body: SignRequest,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> SignBatchResult:
    """Ставит записи в очередь на подпись сертификатом медика (подписывает Предрейс)."""
    return await SigningService(session, get_predreis_client()).request_signing(
        principal, JournalKind.MEDICAL, body.record_ids
    )


@router.get("/{record_id}", response_model=MedicalOut, summary="Получить запись")
async def get_record(
    record_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> MedicalOut:
    """Возвращает одну запись."""
    return await MedicalService(session).get_out(principal, record_id)


@router.patch("/{record_id}", response_model=MedicalOut, summary="Изменить неподписанную запись")
async def update_record(
    record_id: uuid.UUID,
    body: MedicalRecordUpdate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> MedicalOut:
    """Изменяет запись типа А."""
    return await MedicalService(session).update(principal, record_id, body)


@router.delete(
    "/{record_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить неподписанную запись"
)
async def delete_record(
    record_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Удаляет запись типа А."""
    await MedicalService(session).delete_unsigned(principal, record_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{record_id}/clear-note", response_model=MedicalOut, summary="Снять примечание")
async def clear_note(
    record_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> MedicalOut:
    """Очищает поле «Примечание»."""
    return await MedicalService(session).clear_note_out(principal, record_id)


@router.post(
    "/{record_id}/deletion-request",
    response_model=DeletionRequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Запрос на удаление подписанной записи",
)
async def request_deletion(
    record_id: uuid.UUID,
    body: DeletionRequestIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> DeletionRequestOut:
    """Формирует запрос на удаление подписанной записи (тип Б)."""
    req = await MedicalService(session).request_deletion(principal, record_id, body.reason)
    return DeletionRequestOut.model_validate(req)

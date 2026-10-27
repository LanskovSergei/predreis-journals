"""HTTP-эндпоинты журнала технического контроля."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Principal, get_principal
from app.domain.enums import JournalKind
from app.integrations.predreis.client import SignGateway, get_sign_gateway
from app.models.records import TechnicalRecord
from app.modules.records.schemas import (
    DeleteBatchResult,
    DeletionRequestIn,
    DeletionRequestOut,
    Page,
    PageParams,
    RecordIdsIn,
    SignBatchResult,
    SignRequest,
    StandardTimeOut,
    TechnicalFilters,
    page_params,
)
from app.modules.signing.service import SigningService
from app.modules.technical.schemas import (
    TechnicalRecordCreate,
    TechnicalRecordOut,
    TechnicalRecordUpdate,
)
from app.modules.technical.service import TechnicalService

router = APIRouter(prefix="/technical/records", tags=["Журнал техконтроля"])


@router.get("", response_model=Page[TechnicalRecordOut], summary="Архив записей техконтроля")
async def list_records(
    filters: Annotated[TechnicalFilters, Query()],
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Page[TechnicalRecordOut]:
    """Возвращает страницу архива с фильтрами."""
    return await TechnicalService(session).list_records(principal, filters, params)


@router.post(
    "",
    response_model=TechnicalRecordOut,
    status_code=status.HTTP_201_CREATED,
    summary="Создать запись",
)
async def create_record(
    body: TechnicalRecordCreate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> TechnicalRecordOut:
    """Создаёт неподписанную запись техконтроля."""
    return await TechnicalService(session).create(principal, body)


@router.post(
    "/sign", response_model=SignBatchResult, summary="Отправить записи на подпись (в т.ч. массово)"
)
async def sign_records(
    body: SignRequest,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    gateway: SignGateway = Depends(get_sign_gateway),
) -> SignBatchResult:
    """Ставит записи в очередь на подпись сертификатом механика (подписывает Предрейс)."""
    return await SigningService(session, gateway).request_signing(
        principal, JournalKind.TECHNICAL, body.record_ids
    )


@router.get(
    "/standard-time",
    response_model=StandardTimeOut,
    summary="Стандартное время осмотра (последняя запись по ТС)",
)
async def standard_time(
    vehicle_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> StandardTimeOut:
    """Время последней записи из бумажного путевого листа для подстановки в форму создания."""
    conditions = [TechnicalRecord.vehicle_id == vehicle_id]
    return await TechnicalService(session).standard_time(principal, *conditions)


@router.post(
    "/delete",
    response_model=DeleteBatchResult,
    summary="Удалить выбранные неподписанные записи (до 50)",
)
async def delete_records(
    body: RecordIdsIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> DeleteBatchResult:
    """Удаляет выбранные записи типа А; по каждой записи — результат или причина отказа."""
    return await TechnicalService(session).delete_unsigned_many(principal, body.record_ids)


@router.get("/{record_id}", response_model=TechnicalRecordOut, summary="Получить запись")
async def get_record(
    record_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> TechnicalRecordOut:
    """Возвращает одну запись."""
    return await TechnicalService(session).get_out(principal, record_id)


@router.patch(
    "/{record_id}", response_model=TechnicalRecordOut, summary="Изменить неподписанную запись"
)
async def update_record(
    record_id: uuid.UUID,
    body: TechnicalRecordUpdate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> TechnicalRecordOut:
    """Изменяет запись типа А."""
    return await TechnicalService(session).update(principal, record_id, body)


@router.delete(
    "/{record_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить неподписанную запись"
)
async def delete_record(
    record_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Удаляет запись типа А."""
    await TechnicalService(session).delete_unsigned(principal, record_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{record_id}/clear-note", response_model=TechnicalRecordOut, summary="Снять примечание"
)
async def clear_note(
    record_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> TechnicalRecordOut:
    """Очищает поле «Примечание»."""
    return await TechnicalService(session).clear_note_out(principal, record_id)


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
    req = await TechnicalService(session).request_deletion(principal, record_id, body.reason)
    return DeletionRequestOut.model_validate(req)

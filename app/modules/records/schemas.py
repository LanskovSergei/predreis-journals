"""Общие схемы журналов: пагинация, подпись, фильтры, пакетная подпись, удаление."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.domain.enums import InspectionResult

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Страница списка (по ТЗ — 10 строк на страницу по умолчанию)."""

    items: list[T]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True, slots=True)
class PageParams:
    """Параметры пагинации."""

    page: int
    page_size: int

    @property
    def offset(self) -> int:
        """Смещение выборки."""
        return (self.page - 1) * self.page_size


def page_params(
    page: int = Query(1, ge=1),
    page_size: int = Query(
        get_settings().page_size_default, ge=1, le=get_settings().page_size_max
    ),
) -> PageParams:
    """Зависимость FastAPI: параметры пагинации из query."""
    return PageParams(page=page, page_size=page_size)


class SignatureInfo(BaseModel):
    """Данные электронной подписи записи (для таблицы архива)."""

    cert_serial: str | None
    cert_subject: str | None
    cert_valid_from: datetime | None
    cert_valid_to: datetime | None
    signed_at: datetime | None


class RecordFilters(BaseModel):
    """Общие фильтры архива."""

    organization_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    specialist_user_id: uuid.UUID | None = None
    result: InspectionResult | None = None
    has_note: bool | None = None
    is_signed: bool | None = None


class MedicalFilters(RecordFilters):
    """Фильтры журнала медосмотров."""

    driver_id: uuid.UUID | None = Field(
        default=None, description="Записи одного водителя (быстро)"
    )
    driver_name: str | None = Field(
        default=None,
        min_length=3,
        max_length=255,
        description="Поиск по подстроке ФИО, от 3 символов",
    )


class TechnicalFilters(RecordFilters):
    """Фильтры журнала техконтроля."""

    vehicle_id: uuid.UUID | None = Field(default=None, description="Записи одного ТС (быстро)")
    plate: str | None = Field(
        default=None,
        min_length=3,
        max_length=16,
        description="Поиск по подстроке госномера, от 3 символов",
    )


class SignRequest(BaseModel):
    """Запрос на подпись одной или нескольких записей."""

    record_ids: list[uuid.UUID] = Field(min_length=1)


class SignOutcome(BaseModel):
    """Результат подписи одной записи."""

    record_id: uuid.UUID
    ok: bool
    code: str | None = None
    message: str | None = None


class SignBatchResult(BaseModel):
    """Итог пакетной подписи."""

    signed: int
    failed: int
    results: list[SignOutcome]


class DeletionRequestIn(BaseModel):
    """Тело запроса на удаление подписанной записи."""

    reason: str | None = Field(default=None, max_length=1000)


class DeletionRequestOut(BaseModel):
    """Запрос на удаление."""

    id: uuid.UUID
    record_kind: str
    record_id: uuid.UUID
    status: str
    requested_by: uuid.UUID
    reason: str | None
    created_at: datetime
    resolved_at: datetime | None
    resolution_comment: str | None

    model_config = {"from_attributes": True}

"""Схемы журнала технического контроля."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import InspectionResult, RecordSource, RecordStatus, WaybillKind
from app.modules.medical.schemas import _ensure_aware, _normalize_note
from app.modules.records.schemas import SignatureInfo


class TechnicalRecordCreate(BaseModel):
    """Создание записи техконтроля (аналог формы в ЛК Механика, ТЗ стр. 11)."""

    organization_id: uuid.UUID
    vehicle_id: uuid.UUID
    driver_id: uuid.UUID | None = None
    specialist_user_id: uuid.UUID | None = Field(
        default=None, description="Обязателен для менеджеров; для механика — он сам"
    )
    performed_at: datetime
    odometer: int = Field(ge=0, le=10_000_000)
    result: InspectionResult
    note: str | None = None

    _v_note = field_validator("note")(_normalize_note)
    _v_dt = field_validator("performed_at")(_ensure_aware)


class TechnicalRecordUpdate(BaseModel):
    """Частичное изменение неподписанной записи."""

    organization_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    specialist_user_id: uuid.UUID | None = None
    performed_at: datetime | None = None
    odometer: int | None = Field(default=None, ge=0, le=10_000_000)
    result: InspectionResult | None = None
    note: str | None = None

    _v_note = field_validator("note")(_normalize_note)
    _v_dt = field_validator("performed_at")(_ensure_aware)


class TechnicalRecordOut(BaseModel):
    """Представление записи техконтроля."""

    id: uuid.UUID
    status: RecordStatus
    source: RecordSource
    waybill_kind: WaybillKind
    organization_id: uuid.UUID
    vehicle_id: uuid.UUID
    driver_id: uuid.UUID | None
    specialist_user_id: uuid.UUID
    performed_at: datetime
    snapshot: dict[str, Any]
    odometer: int
    result: InspectionResult
    note: str | None
    has_note: bool
    deletion_pending: bool
    in_journal_reserved: bool
    signature: SignatureInfo | None
    signing_status: str | None = None
    signing_error: str | None = None
    actions: list[str]

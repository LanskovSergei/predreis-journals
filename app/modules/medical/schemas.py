"""Схемы журнала медицинских осмотров."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import (
    Gender,
    HarmfulFactors,
    InspectionPhase,
    InspectionResult,
    RecordSource,
    RecordStatus,
    WaybillKind,
)
from app.modules.records.schemas import SignatureInfo


def _normalize_note(value: str | None) -> str | None:
    """Пустое примечание хранится как NULL."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _ensure_aware(value: datetime | None) -> datetime | None:
    """Требует дату и время с часовым поясом."""
    if value is not None and value.tzinfo is None:
        raise ValueError("Укажите дату и время с часовым поясом (например, +03:00)")
    return value


class MedicalRecordCreate(BaseModel):
    """Создание записи медосмотра (аналог формы в ЛК Медика, ТЗ стр. 9)."""

    organization_id: uuid.UUID
    driver_id: uuid.UUID
    specialist_user_id: uuid.UUID | None = Field(
        default=None, description="Обязателен для менеджеров; для медика — он сам"
    )
    phase: InspectionPhase
    performed_at: datetime
    complaints: str = Field(default="отсутствуют", min_length=1)
    bp_systolic: int = Field(ge=50, le=300)
    bp_diastolic: int = Field(ge=30, le=200)
    pulse: int = Field(ge=20, le=250)
    temperature: Decimal = Field(ge=30, le=45, decimal_places=1)
    alcohol_mgl: Decimal = Field(default=Decimal("0.00"), ge=0, le=5, decimal_places=2)
    harmful_factors: HarmfulFactors = HarmfulFactors.ABSENT
    harmful_factors_note: str | None = None
    result: InspectionResult
    note: str | None = None

    _v_note = field_validator("note")(_normalize_note)
    _v_dt = field_validator("performed_at")(_ensure_aware)


class MedicalRecordUpdate(BaseModel):
    """Частичное изменение неподписанной записи."""

    organization_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    specialist_user_id: uuid.UUID | None = None
    phase: InspectionPhase | None = None
    performed_at: datetime | None = None
    complaints: str | None = Field(default=None, min_length=1)
    bp_systolic: int | None = Field(default=None, ge=50, le=300)
    bp_diastolic: int | None = Field(default=None, ge=30, le=200)
    pulse: int | None = Field(default=None, ge=20, le=250)
    temperature: Decimal | None = Field(default=None, ge=30, le=45, decimal_places=1)
    alcohol_mgl: Decimal | None = Field(default=None, ge=0, le=5, decimal_places=2)
    harmful_factors: HarmfulFactors | None = None
    harmful_factors_note: str | None = None
    result: InspectionResult | None = None
    note: str | None = None

    _v_note = field_validator("note")(_normalize_note)
    _v_dt = field_validator("performed_at")(_ensure_aware)


class MedicalRecordOut(BaseModel):
    """Полное представление записи (для медиков и менеджеров)."""

    id: uuid.UUID
    status: RecordStatus
    source: RecordSource
    waybill_kind: WaybillKind
    phase: InspectionPhase
    organization_id: uuid.UUID
    driver_id: uuid.UUID
    specialist_user_id: uuid.UUID
    performed_at: datetime
    snapshot: dict[str, Any]
    complaints: str
    bp_systolic: int
    bp_diastolic: int
    pulse: int
    temperature: Decimal
    alcohol_mgl: Decimal
    harmful_factors: HarmfulFactors
    harmful_factors_note: str | None
    result: InspectionResult
    note: str | None
    has_note: bool
    deletion_pending: bool
    in_journal_reserved: bool
    signature: SignatureInfo | None
    actions: list[str]


class MedicalRecordClientOut(BaseModel):
    """Представление для клиента/диспетчера: поля врачебной тайны отсутствуют целиком."""

    id: uuid.UUID
    status: RecordStatus
    source: RecordSource
    waybill_kind: WaybillKind
    phase: InspectionPhase
    performed_at: datetime
    driver_full_name: str
    driver_birth_date: date | None
    driver_gender: Gender | None
    specialist_name: str | None
    result: InspectionResult
    signature: SignatureInfo | None

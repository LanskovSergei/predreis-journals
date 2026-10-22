"""Схемы электронных журналов (ZIP-контейнеров)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from app.domain.enums import EJournalStatus, JournalKind


class EJournalCreate(BaseModel):
    """Параметры формирования электронного журнала: организация + период."""

    kind: JournalKind
    organization_id: uuid.UUID
    period_from: date
    period_to: date

    @model_validator(mode="after")
    def _check_period(self) -> EJournalCreate:
        """Начало периода не позже конца."""
        if self.period_from > self.period_to:
            raise ValueError("period_from не может быть позже period_to")
        return self


class EJournalOut(BaseModel):
    """Электронный журнал."""

    id: uuid.UUID
    kind: JournalKind
    organization_id: uuid.UUID
    period_from: date
    period_to: date
    status: EJournalStatus
    record_count: int
    created_by: uuid.UUID
    submitted_at: datetime | None
    signed_by: uuid.UUID | None
    signed_at: datetime | None
    reject_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RejectIn(BaseModel):
    """Причина отклонения журнала."""

    reason: str | None = Field(default=None, max_length=1000)

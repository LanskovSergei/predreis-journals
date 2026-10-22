"""Схемы распознавания сканов путевых листов."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.domain.enums import JournalKind, OcrBatchStatus, OcrStampType


class OcrBatchOut(BaseModel):
    """Пакет распознавания."""

    id: uuid.UUID
    kind: JournalKind
    stamp_type: OcrStampType
    status: OcrBatchStatus
    created_at: datetime

    model_config = {"from_attributes": True}

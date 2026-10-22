"""Распознавание сканов бумажных путевых листов (Yandex Vision OCR)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import JournalKind, OcrBatchStatus, OcrStampType
from app.models.base import Base, TimestampMixin, enum_col


class OcrBatch(TimestampMixin, Base):
    """Пакет загруженных сканов."""

    __tablename__ = "ocr_batches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[JournalKind] = mapped_column(enum_col(JournalKind))
    stamp_type: Mapped[OcrStampType] = mapped_column(enum_col(OcrStampType))
    status: Mapped[OcrBatchStatus] = mapped_column(
        enum_col(OcrBatchStatus), default=OcrBatchStatus.UPLOADED
    )
    created_by: Mapped[uuid.UUID] = mapped_column()
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class OcrItem(TimestampMixin, Base):
    """Черновик строки журнала, полученный из скана."""

    __tablename__ = "ocr_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ocr_batches.id", ondelete="CASCADE"), index=True
    )
    row_no: Mapped[int] = mapped_column(Integer)
    parsed: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(32), default="draft")

"""Электронные документы: подписи записей, электронные журналы, запросы на удаление."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import DeletionStatus, EJournalStatus, JournalKind
from app.models.base import Base, TimestampMixin, enum_col


class RecordDocument(TimestampMixin, Base):
    """Электронный документ типа 1: XML + PDF + откреплённая подпись + TSP."""

    __tablename__ = "record_documents"
    __table_args__ = (UniqueConstraint("record_kind", "record_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    record_kind: Mapped[JournalKind] = mapped_column(enum_col(JournalKind))
    record_id: Mapped[uuid.UUID] = mapped_column()
    xml_key: Mapped[str | None] = mapped_column(Text)
    pdf_key: Mapped[str | None] = mapped_column(Text)
    sig_key: Mapped[str | None] = mapped_column(Text)
    tsp_key: Mapped[str | None] = mapped_column(Text)
    xml_sha256: Mapped[str | None] = mapped_column(String(64))
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    signer_user_id: Mapped[uuid.UUID | None] = mapped_column()
    cert_serial: Mapped[str | None] = mapped_column(String(128))
    cert_subject: Mapped[str | None] = mapped_column(Text)
    cert_valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cert_valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ocsp_status: Mapped[str | None] = mapped_column(String(32))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EJournal(TimestampMixin, Base):
    """Электронный журнал (документ типа 2): ZIP-контейнер, подписанный УКЭП организации."""

    __tablename__ = "e_journals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[JournalKind] = mapped_column(enum_col(JournalKind))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    status: Mapped[EJournalStatus] = mapped_column(
        enum_col(EJournalStatus), default=EJournalStatus.DRAFT, index=True
    )
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_by: Mapped[uuid.UUID | None] = mapped_column()
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[uuid.UUID | None] = mapped_column()
    reject_reason: Mapped[str | None] = mapped_column(Text)
    xml_key: Mapped[str | None] = mapped_column(Text)
    pdf_key: Mapped[str | None] = mapped_column(Text)
    sig_key: Mapped[str | None] = mapped_column(Text)
    zip_key: Mapped[str | None] = mapped_column(Text)
    zip_sha256: Mapped[str | None] = mapped_column(String(64))
    xml_sha256: Mapped[str | None] = mapped_column(String(64))
    tsp_key: Mapped[str | None] = mapped_column(Text)
    preview_pdf_key: Mapped[str | None] = mapped_column(Text)
    audit_key: Mapped[str | None] = mapped_column(Text)
    cert_serial: Mapped[str | None] = mapped_column(String(128))
    cert_subject: Mapped[str | None] = mapped_column(Text)
    cert_valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cert_valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ocsp_status: Mapped[str | None] = mapped_column(String(32))
    package: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class EJournalItem(Base):
    """Запись, включённая в электронный журнал. Одна запись — не более чем в одном журнале."""

    __tablename__ = "e_journal_items"
    __table_args__ = (UniqueConstraint("record_kind", "record_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    journal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("e_journals.id", ondelete="CASCADE"), index=True
    )
    record_kind: Mapped[JournalKind] = mapped_column(enum_col(JournalKind))
    record_id: Mapped[uuid.UUID] = mapped_column()


class DeletionRequest(TimestampMixin, Base):
    """Запрос на удаление подписанной записи (тип Б), подтверждается Админом/СА."""

    __tablename__ = "deletion_requests"
    __table_args__ = (
        Index(
            "uq_deletion_requests_pending",
            "record_kind",
            "record_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    record_kind: Mapped[JournalKind] = mapped_column(enum_col(JournalKind))
    record_id: Mapped[uuid.UUID] = mapped_column()
    status: Mapped[DeletionStatus] = mapped_column(
        enum_col(DeletionStatus), default=DeletionStatus.PENDING
    )
    requested_by: Mapped[uuid.UUID] = mapped_column()
    reason: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_comment: Mapped[str | None] = mapped_column(Text)

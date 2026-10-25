"""Записи архива: журнал медосмотров и журнал техконтроля."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.domain.enums import (
    HarmfulFactors,
    InspectionPhase,
    InspectionResult,
    JournalKind,
    RecordSource,
    RecordStatus,
    WaybillKind,
)
from app.models.base import Base, TimestampMixin, enum_col


class RecordMixin(TimestampMixin):
    """Общие колонки записи архива. Реквизиты фиксируются в snapshot на момент осмотра."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    status: Mapped[RecordStatus] = mapped_column(
        enum_col(RecordStatus), default=RecordStatus.UNSIGNED, server_default="unsigned"
    )
    source: Mapped[RecordSource] = mapped_column(enum_col(RecordSource))
    epl_waybill_id: Mapped[uuid.UUID | None] = mapped_column()
    epl_title_number: Mapped[int | None] = mapped_column(SmallInteger)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(Text)
    deletion_pending: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    record_hash: Mapped[str | None] = mapped_column(String(64))
    gis_uid: Mapped[str | None] = mapped_column(String(64))
    waybill_number: Mapped[str | None] = mapped_column(String(64))
    epl_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column()

    @declared_attr
    def organization_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        """Организация, для которой проведён осмотр."""
        return mapped_column(ForeignKey("organizations.id"))

    @declared_attr
    def specialist_user_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        """Медик/механик, проводивший осмотр (обязательное поле)."""
        return mapped_column(ForeignKey("users.id"))

    @declared_attr
    def reserved_journal_id(cls) -> Mapped[uuid.UUID | None]:  # noqa: N805
        """Электронный журнал, в который запись зарезервирована/включена."""
        return mapped_column(ForeignKey("e_journals.id", ondelete="SET NULL"))

    @property
    def waybill_kind(self) -> WaybillKind:
        """Вид путевого листа, производный от источника."""
        return WaybillKind.EPL if self.source is RecordSource.EPL else WaybillKind.PAPER


class MedicalRecord(RecordMixin, Base):
    """Запись журнала медицинских осмотров."""

    __tablename__ = "medical_records"
    __table_args__ = (
        UniqueConstraint("epl_waybill_id", "epl_title_number"),
        Index("ix_medical_records_org_performed", "organization_id", "performed_at"),
        Index("ix_medical_records_status", "status"),
        Index("ix_medical_records_specialist", "specialist_user_id", "status"),
    )

    phase: Mapped[InspectionPhase] = mapped_column(enum_col(InspectionPhase))
    driver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drivers.id"), index=True)
    complaints: Mapped[str] = mapped_column(Text)
    bp_systolic: Mapped[int] = mapped_column(SmallInteger)
    bp_diastolic: Mapped[int] = mapped_column(SmallInteger)
    pulse: Mapped[int] = mapped_column(SmallInteger)
    temperature: Mapped[Decimal] = mapped_column(Numeric(3, 1))
    alcohol_mgl: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    # None — признак не определялся (автоматический осмотр «Водителя+» без живого медика).
    harmful_factors: Mapped[HarmfulFactors | None] = mapped_column(enum_col(HarmfulFactors))
    harmful_factors_note: Mapped[str | None] = mapped_column(Text)
    result: Mapped[InspectionResult] = mapped_column(enum_col(InspectionResult))


class TechnicalRecord(RecordMixin, Base):
    """Запись журнала технического контроля."""

    __tablename__ = "technical_records"
    __table_args__ = (
        UniqueConstraint("epl_waybill_id", "epl_title_number"),
        Index("ix_technical_records_org_performed", "organization_id", "performed_at"),
        Index("ix_technical_records_status", "status"),
        Index("ix_technical_records_specialist", "specialist_user_id", "status"),
        Index("ix_technical_records_vehicle_performed", "vehicle_id", "performed_at"),
    )

    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"))
    driver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drivers.id"))
    odometer: Mapped[int] = mapped_column(Integer)
    result: Mapped[InspectionResult] = mapped_column(enum_col(InspectionResult))


AnyRecord = MedicalRecord | TechnicalRecord


def record_model(kind: JournalKind) -> type[MedicalRecord] | type[TechnicalRecord]:
    """Возвращает модель записи по виду журнала."""
    return MedicalRecord if kind is JournalKind.MEDICAL else TechnicalRecord

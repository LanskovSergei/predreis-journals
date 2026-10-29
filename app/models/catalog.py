"""Реплики справочников Предрейса. PK = идентификатор сущности в Предрейсе."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import CatalogOrigin, ContractType, Gender, Role, WorkFormat
from app.models.base import Base, TimestampMixin, enum_col


class Organization(TimestampMixin, Base):
    """Организация-клиент (реплика)."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    inn: Mapped[str] = mapped_column(String(12), index=True)
    legal_form: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(512), index=True)
    short_name: Mapped[str | None] = mapped_column(String(512))
    kpp: Mapped[str | None] = mapped_column(String(9))
    ogrn: Mapped[str | None] = mapped_column(String(15))
    legal_address: Mapped[str | None] = mapped_column(Text)
    head_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    contract_type: Mapped[ContractType | None] = mapped_column(enum_col(ContractType))
    contract_number: Mapped[str | None] = mapped_column(String(128))
    contract_date: Mapped[date | None] = mapped_column(Date)
    contract_until: Mapped[date | None] = mapped_column(Date)
    work_format: Mapped[WorkFormat] = mapped_column(
        enum_col(WorkFormat), default=WorkFormat.EPL, server_default="epl"
    )
    # Откуда карточка. Идентификатор Предрейса хранится отдельно: у карточки, добавленной вручную
    # и затем объединённой с платформой, наш id не меняется (на него ссылаются записи).
    origin: Mapped[CatalogOrigin] = mapped_column(
        enum_col(CatalogOrigin), default=CatalogOrigin.PLATFORM, server_default="platform"
    )
    predreis_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    note: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Driver(TimestampMixin, Base):
    """Водитель (реплика)."""

    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(255), index=True)
    gender: Mapped[Gender | None] = mapped_column(enum_col(Gender, 1))
    birth_date: Mapped[date | None] = mapped_column(Date)
    snils: Mapped[str | None] = mapped_column(String(14))
    license_number: Mapped[str | None] = mapped_column(String(32))
    license_issued_at: Mapped[date | None] = mapped_column(Date)
    license_valid_until: Mapped[date | None] = mapped_column(Date)
    # Откуда карточка. Идентификатор Предрейса хранится отдельно: у карточки, добавленной вручную
    # и затем объединённой с платформой, наш id не меняется (на него ссылаются записи).
    origin: Mapped[CatalogOrigin] = mapped_column(
        enum_col(CatalogOrigin), default=CatalogOrigin.PLATFORM, server_default="platform"
    )
    predreis_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    note: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Vehicle(TimestampMixin, Base):
    """Транспортное средство (реплика)."""

    __tablename__ = "vehicles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    brand: Mapped[str] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(128))
    vehicle_type: Mapped[str | None] = mapped_column(String(128))
    plate: Mapped[str] = mapped_column(String(16), index=True)
    diag_card_until: Mapped[date | None] = mapped_column(Date)
    # Откуда карточка. Идентификатор Предрейса хранится отдельно: у карточки, добавленной вручную
    # и затем объединённой с платформой, наш id не меняется (на него ссылаются записи).
    origin: Mapped[CatalogOrigin] = mapped_column(
        enum_col(CatalogOrigin), default=CatalogOrigin.PLATFORM, server_default="platform"
    )
    predreis_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    note: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(TimestampMixin, Base):
    """Пользователь платформы (реплика). Доступ к журналам включает суперадмин в Предрейсе."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    role: Mapped[Role] = mapped_column(enum_col(Role))
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    journals_access: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

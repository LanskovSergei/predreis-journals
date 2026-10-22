"""Схемы каталога организаций, водителей и ТС."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import ContractType, Gender, WorkFormat
from app.domain.validators import validate_snils


class OrganizationOut(BaseModel):
    """Организация в каталоге."""

    id: uuid.UUID
    inn: str
    legal_form: str | None
    name: str
    short_name: str | None
    kpp: str | None
    ogrn: str | None
    legal_address: str | None
    head_name: str | None
    email: str | None
    phone: str | None
    contract_type: ContractType | None
    contract_number: str | None
    contract_date: date | None
    contract_until: date | None
    work_format: WorkFormat
    is_active: bool
    note: str | None

    model_config = {"from_attributes": True}


class DriverOut(BaseModel):
    """Водитель в каталоге."""

    id: uuid.UUID
    organization_id: uuid.UUID
    full_name: str
    gender: Gender
    birth_date: date
    snils: str | None
    license_number: str | None
    license_issued_at: date | None
    license_valid_until: date | None
    is_active: bool
    note: str | None

    model_config = {"from_attributes": True}


class VehicleOut(BaseModel):
    """ТС в каталоге."""

    id: uuid.UUID
    organization_id: uuid.UUID
    brand: str
    model: str
    vehicle_type: str | None
    plate: str
    diag_card_until: date | None
    is_active: bool
    note: str | None

    model_config = {"from_attributes": True}


class OrganizationCreate(BaseModel):
    """Создание организации: реквизиты Предрейс подтянет по ИНН сам."""

    inn: str = Field(pattern=r"^\d{10}(\d{2})?$")
    email: str | None = None
    phone: str | None = None
    contract_type: ContractType
    contract_number: str | None = None
    contract_date: date | None = None
    contract_until: date | None = None
    note: str | None = None


class DriverCreate(BaseModel):
    """Создание водителя."""

    organization_id: uuid.UUID
    full_name: str = Field(min_length=3, max_length=255)
    gender: Gender
    birth_date: date
    snils: str | None = None
    license_number: str | None = None
    license_issued_at: date | None = None
    license_valid_until: date | None = None

    @field_validator("snils")
    @classmethod
    def _check_snils(cls, value: str | None) -> str | None:
        """Проверяет контрольное число СНИЛС."""
        if value is not None and not validate_snils(value):
            raise ValueError("Некорректный СНИЛС")
        return value


class VehicleCreate(BaseModel):
    """Создание ТС."""

    organization_id: uuid.UUID
    brand: str
    model: str
    vehicle_type: str | None = None
    plate: str = Field(min_length=3, max_length=16)
    diag_card_until: date | None = None

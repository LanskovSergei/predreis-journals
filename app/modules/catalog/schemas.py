"""Схемы каталога организаций, водителей и ТС."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import CatalogOrigin, ContractType, Gender, WorkFormat
from app.domain.validators import normalize_plate, validate_inn, validate_snils


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
    origin: CatalogOrigin
    is_active: bool
    note: str | None

    model_config = {"from_attributes": True}


class DriverOut(BaseModel):
    """Водитель в каталоге."""

    id: uuid.UUID
    organization_id: uuid.UUID
    full_name: str
    gender: Gender | None
    birth_date: date | None
    snils: str | None
    license_number: str | None
    license_issued_at: date | None
    license_valid_until: date | None
    origin: CatalogOrigin
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
    origin: CatalogOrigin
    is_active: bool
    note: str | None

    model_config = {"from_attributes": True}


DEFAULT_CONTRACT_UNTIL = date(2026, 12, 31)  # ТЗ, стр. 15: «по умолчанию до 31.12.2026»


def _clean(value: str | None) -> str | None:
    """Пустая строка — отсутствие значения."""
    if value is None:
        return None
    value = value.strip()
    return value or None


class _OrganizationFields(BaseModel):
    """Поля карточки организации (общие для создания и правки)."""

    legal_form: str | None = Field(default=None, max_length=32)
    short_name: str | None = Field(default=None, max_length=512)
    kpp: str | None = Field(default=None, pattern=r"^\d{9}$")
    ogrn: str | None = Field(default=None, pattern=r"^(\d{13}|\d{15})$")
    legal_address: str | None = None
    head_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str | None = Field(default=None, max_length=64)
    contract_type: ContractType | None = None
    contract_number: str | None = Field(default=None, max_length=128)
    contract_date: date | None = None
    note: str | None = None


class OrganizationCreate(_OrganizationFields):
    """Организация, добавляемая вручную (бумажный клиент)."""

    inn: str = Field(
        description="10 цифр (организация) или 12 (ИП), проверяются контрольные разряды"
    )
    name: str = Field(min_length=1, max_length=512)
    contract_until: date | None = DEFAULT_CONTRACT_UNTIL

    @field_validator("inn")
    @classmethod
    def _inn(cls, value: str) -> str:
        """ИНН с верными контрольными разрядами."""
        value = value.strip()
        if not validate_inn(value):
            raise ValueError("Неверный ИНН: нужно 10 или 12 цифр с верными контрольными разрядами")
        return value


class OrganizationUpdate(_OrganizationFields):
    """Правка карточки: у организаций из платформы меняются только поля журналов."""

    inn: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=512)
    contract_until: date | None = None
    is_active: bool | None = None

    @field_validator("inn")
    @classmethod
    def _inn(cls, value: str | None) -> str | None:
        """ИНН с верными контрольными разрядами."""
        if value is not None and not validate_inn(value.strip()):
            raise ValueError("Неверный ИНН: нужно 10 или 12 цифр с верными контрольными разрядами")
        return value.strip() if value else value


class _DriverFields(BaseModel):
    """Поля карточки водителя."""

    gender: Gender | None = None
    birth_date: date | None = None
    snils: str | None = Field(default=None, description="СНИЛС, проверяется контрольное число")
    license_number: str | None = Field(default=None, max_length=32)
    license_issued_at: date | None = None
    license_valid_until: date | None = None
    note: str | None = None

    @field_validator("snils")
    @classmethod
    def _snils(cls, value: str | None) -> str | None:
        """СНИЛС с верным контрольным числом."""
        value = _clean(value)
        if value is not None and not validate_snils(value):
            raise ValueError("Неверный СНИЛС: не сходится контрольное число")
        return value


class DriverCreate(_DriverFields):
    """Водитель, добавляемый вручную (к любой организации, в т. ч. из платформы)."""

    organization_id: uuid.UUID
    full_name: str = Field(min_length=3, max_length=255)


class DriversCreate(BaseModel):
    """До 10 водителей за раз (ТЗ, стр. 16)."""

    drivers: list[DriverCreate] = Field(min_length=1, max_length=10)


class DriverUpdate(_DriverFields):
    """Правка водителя: у водителей из платформы меняются только поля журналов."""

    full_name: str | None = Field(default=None, min_length=3, max_length=255)
    is_active: bool | None = None


class _VehicleFields(BaseModel):
    """Поля карточки ТС."""

    vehicle_type: str | None = Field(default=None, max_length=128)
    diag_card_until: date | None = None
    note: str | None = None


class VehicleCreate(_VehicleFields):
    """ТС, добавляемое вручную."""

    organization_id: uuid.UUID
    brand: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    plate: str = Field(
        min_length=4, max_length=16, description="Госномер; пробелы и регистр не важны"
    )

    @field_validator("plate")
    @classmethod
    def _plate(cls, value: str) -> str:
        """Госномер единым видом (латиница заменяется кириллицей)."""
        return normalize_plate(value)


class VehiclesCreate(BaseModel):
    """До 10 ТС за раз (ТЗ, стр. 16)."""

    vehicles: list[VehicleCreate] = Field(min_length=1, max_length=10)


class VehicleUpdate(_VehicleFields):
    """Правка ТС: у ТС из платформы меняются только поля журналов."""

    brand: str | None = Field(default=None, min_length=1, max_length=128)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    plate: str | None = Field(default=None, min_length=4, max_length=16)
    is_active: bool | None = None

    @field_validator("plate")
    @classmethod
    def _plate(cls, value: str | None) -> str | None:
        """Госномер единым видом."""
        return normalize_plate(value) if value else value

"""Схемы каталога организаций, водителей и ТС."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel

from app.domain.enums import ContractType, Gender, WorkFormat


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
    gender: Gender | None
    birth_date: date | None
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

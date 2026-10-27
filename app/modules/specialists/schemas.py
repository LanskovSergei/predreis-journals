"""Схемы ответов: сертификаты и список специалистов."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

CertStatusLiteral = Literal["active", "expired", "missing"]


class CertificateOut(BaseModel):
    """Сертификат пользователя: статус считается по сроку и признаку `is_valid` Предрейса."""

    serial: str | None
    owner: str | None
    thumbprint: str | None
    issuer: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    status: CertStatusLiteral
    expiring_soon: bool


class MyCertificatesOut(BaseModel):
    """Сертификаты текущего специалиста (стартовая страница медика и механика)."""

    status: CertStatusLiteral
    valid_to: datetime | None
    certificates: list[CertificateOut]
    revocation_checked: bool = False


class RecordCounters(BaseModel):
    """Счётчики записей специалиста: «на подпись / подписанных / всего»."""

    to_sign: int
    signed: int
    total: int


class SpecialistOut(BaseModel):
    """Специалист (медик или механик): сертификат и, для СА, счётчики записей."""

    user_id: uuid.UUID
    full_name: str
    role: Literal["medic", "mechanic"]
    status: CertStatusLiteral
    valid_to: datetime | None
    expiring_soon: bool
    certificates: list[CertificateOut]
    records: RecordCounters | None = None


class SpecialistsOut(BaseModel):
    """Список специалистов; `certificates_available=false`, если Предрейс не ответил."""

    items: list[SpecialistOut]
    certificates_available: bool
    revocation_checked: bool = False

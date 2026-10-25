"""Схемы данных Предрейса: справочники и нормализованное ЭПЛ-событие.

Справочники читаются по pull (changed_after), поля принимают несколько вариантов названий
(`validation_alias`), потому что точный формат ответа сверяется по образцам Предрейса.
Нормализованное событие `EplRecordEvent` — внутренний формат; из сообщений очереди его строит
`events.map_envelope`.
"""

from __future__ import annotations

import base64
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import ContractType, Gender, HarmfulFactors, Role, WorkFormat
from app.integrations.predreis.signature import is_placeholder

_OFFSET_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")
_MALE = {"m", "male", "м", "муж", "мужской", "man"}
_FEMALE = {"f", "female", "ж", "жен", "женский", "woman"}


def normalize_gender(value: Any) -> Gender | None:
    """Приводит пол из разных обозначений к M/F; неизвестное значение — None (пол не угадываем)."""
    if isinstance(value, Gender):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in _MALE:
        return Gender.MALE
    if text in _FEMALE:
        return Gender.FEMALE
    return None


class _CatalogBase(BaseModel):
    """Общие настройки схем справочников: допускаем и имена полей, и их синонимы."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class OrganizationPayload(_CatalogBase):
    """Организация. Договорных данных Предрейс не отдаёт — они необязательны."""

    id: uuid.UUID
    inn: str
    kpp: str | None = None
    ogrn: str | None = None
    name: str = Field(validation_alias=AliasChoices("name", "full_name", "name_full"))
    short_name: str | None = Field(
        default=None, validation_alias=AliasChoices("short_name", "name_short")
    )
    legal_address: str | None = Field(
        default=None, validation_alias=AliasChoices("legal_address", "address")
    )
    is_active: bool = Field(default=True, validation_alias=AliasChoices("is_active", "active"))
    updated_at: datetime | None = None
    # Не приходят из Предрейса; задаются в журналах/тестах и не затираются синхронизацией.
    work_format: WorkFormat | None = None
    contract_type: ContractType | None = None
    legal_form: str | None = None
    head_name: str | None = None
    email: str | None = None
    phone: str | None = None
    note: str | None = None


class DriverPayload(_CatalogBase):
    """Водитель. Пол и права могут быть пустыми или в одном поле («9910 915125»)."""

    id: uuid.UUID
    organization_id: uuid.UUID = Field(validation_alias=AliasChoices("organization_id", "org_id"))
    full_name: str
    gender: Gender | None = Field(default=None, validation_alias=AliasChoices("gender", "sex"))
    birth_date: date | None = Field(
        default=None, validation_alias=AliasChoices("birth_date", "birthday", "date_of_birth")
    )
    license_number: str | None = Field(
        default=None, validation_alias=AliasChoices("license_number", "license", "driver_license")
    )
    snils: str | None = None
    is_active: bool = Field(default=True, validation_alias=AliasChoices("is_active", "active"))
    updated_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _compose(cls, data: Any) -> Any:
        """Собирает ФИО из частей и права из серии и номера, если они пришли раздельно."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if not data.get("full_name"):
            parts = (data.get("last_name"), data.get("first_name"), data.get("middle_name"))
            data["full_name"] = " ".join(str(p) for p in parts if p) or data.get("name")
        series, number = data.get("license_series"), data.get("license_number")
        if series and number and not data.get("license"):
            data["license_number"] = f"{series} {number}"
        return data

    @field_validator("gender", mode="before")
    @classmethod
    def _gender(cls, value: Any) -> Gender | None:
        """Нормализует пол."""
        return normalize_gender(value)


class VehiclePayload(_CatalogBase):
    """Транспортное средство."""

    id: uuid.UUID
    organization_id: uuid.UUID = Field(validation_alias=AliasChoices("organization_id", "org_id"))
    plate: str = Field(
        validation_alias=AliasChoices("plate_number", "plate", "license_plate", "gos_number")
    )
    brand: str = Field(validation_alias=AliasChoices("brand", "make"))
    model: str
    vehicle_type: str | None = Field(
        default=None, validation_alias=AliasChoices("vehicle_type", "type")
    )
    is_active: bool = Field(default=True, validation_alias=AliasChoices("is_active", "active"))
    updated_at: datetime | None = None


class UserPayload(BaseModel):
    """Специалист или пользователь для реплики `users` (из событий и токена, не из справочника)."""

    id: uuid.UUID
    role: Role
    full_name: str
    email: str | None = None
    organization_id: uuid.UUID | None = None
    journals_access: bool = False
    is_active: bool = True


MEDICAL_DETAIL_FIELDS = (
    "alcohol_detected",
    "harmful_factors",
    "critical_flag",
    "recorded_at",
    "medic_license_series",
    "medic_license_number",
    "medic_license_issued",
    "medic_license_expires",
    "medic_org_name",
    "vid_mo",
    "is_pre_trip",
    "is_post_trip",
    "edweb_document_id",
)
TECHNICAL_DETAIL_FIELDS = (
    "vehicle_type",
    "vehicle_category",
    "brakes_ok",
    "lighting_ok",
    "tires_ok",
    "released",
    "mechanic_position",
    "recorded_at",
    "edweb_document_id",
)


def parse_tz_offset(value: str | int) -> timedelta:
    """Разбирает смещение часового пояса: «+03:00», «+0300» или целое число минут."""
    if isinstance(value, int):
        return timedelta(minutes=value)
    match = _OFFSET_RE.match(value.strip())
    if match is None:
        raise ValueError("exam_tz_offset: ожидается «+03:00», «+0300» или число минут")
    sign = -1 if match.group(1) == "-" else 1
    return sign * timedelta(hours=int(match.group(2)), minutes=int(match.group(3)))


class EplRecordEvent(BaseModel):
    """Нормализованное событие осмотра: T2/T6 — медосмотр, T3 — техконтроль."""

    event_type: Literal["T2", "T3", "T6"]
    event_id: uuid.UUID
    source: Literal["epl"] = "epl"
    waybill_id: uuid.UUID
    waybill_number: str
    gis_uid: str
    qr_issued: bool = True
    edweb_document_id: str | None = None

    # Идентификаторы Предрейса; если их нет, привязка по реквизитам (ИНН, ФИО, госномер).
    organization_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None
    specialist_user_id: uuid.UUID

    org_inn: str
    org_kpp: str | None = None
    org_ogrn: str | None = None
    org_name: str
    org_short_name: str | None = None
    org_address: str | None = None

    driver_last_name: str
    driver_first_name: str
    driver_middle_name: str | None = None
    driver_birth_date: date
    driver_gender: Gender | None = None
    driver_license: str | None = None
    driver_license_series: str | None = None
    driver_license_number: str | None = None

    specialist_last_name: str
    specialist_first_name: str
    specialist_middle_name: str | None = None

    exam_datetime: datetime
    exam_tz_offset: str | int | None = None

    signature_serial: str | None = None
    signature_owner: str | None = None
    signature_valid_from: datetime | None = None
    signature_valid_to: datetime | None = None
    signature_b64: str | None = None
    tsp_b64: str | None = None
    # placeholder — вместо подписи заглушка (AUTO_SIGNATURE); invalid — подпись не в base64.
    signature_state: Literal["placeholder", "invalid"] | None = None

    notes: str | None = None

    # --- только медосмотр (Т2/Т6) ---
    blood_pressure_systolic: int | None = None
    blood_pressure_diastolic: int | None = None
    pulse: int | None = None
    temperature: Decimal | None = None
    alcohol_detected: bool | None = None
    alcohol_ppm: Decimal | None = None
    complaints: str | None = None
    harmful_factors_detected: bool | None = None
    harmful_factors: str | list[str] | None = None
    approved: bool | None = None
    critical_flag: bool | None = None
    recorded_at: datetime | None = None
    medic_license_series: str | None = None
    medic_license_number: str | None = None
    medic_license_issued: date | None = None
    medic_license_expires: date | None = None
    medic_org_name: str | None = None
    vid_mo: str | None = None
    is_pre_trip: bool | None = None
    is_post_trip: bool | None = None

    # --- только техконтроль (Т3) ---
    brakes_ok: bool | None = None
    lighting_ok: bool | None = None
    tires_ok: bool | None = None
    vehicle_plate: str | None = None
    vehicle_brand: str | None = None
    vehicle_model: str | None = None
    vehicle_type: str | None = None
    vehicle_category: str | None = None
    odometer: int | None = None
    released: bool | None = None
    mechanic_position: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_signature(cls, data: Any) -> Any:
        """Заглушка и испорченная подпись не блокируют запись: подпись отбрасывается."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for field in ("signature_b64", "tsp_b64"):
            value = data.get(field)
            if not value:
                continue
            if is_placeholder(value):
                data[field], data["signature_state"] = None, "placeholder"
                continue
            try:
                base64.b64decode(value, validate=True)
            except (ValueError, TypeError):
                data[field], data["signature_state"] = None, "invalid"
        return data

    @model_validator(mode="after")
    def _check_consistency(self) -> EplRecordEvent:
        """Проверяет QR, смещение пояса и комплектность полей для вида титула."""
        if not self.qr_issued:
            raise ValueError("Запись создаётся только после получения QR (qr_issued=true)")
        if self.exam_tz_offset is not None:
            parse_tz_offset(self.exam_tz_offset)
        required: tuple[str, ...]
        if self.event_type == "T3":
            required = ("vehicle_plate", "vehicle_brand", "vehicle_model", "odometer", "approved")
        else:
            required = (
                "blood_pressure_systolic",
                "blood_pressure_diastolic",
                "pulse",
                "temperature",
                "alcohol_ppm",
                "approved",
            )
        missing = [f for f in required if getattr(self, f) is None]
        if missing:
            raise ValueError(f"Для {self.event_type} обязательны поля: {', '.join(missing)}")
        return self

    def performed_at(self, default_tz: timezone | Any) -> datetime:
        """Момент осмотра с часовым поясом (из времени, смещения или местный по умолчанию)."""
        if self.exam_datetime.tzinfo is not None:
            return self.exam_datetime
        if self.exam_tz_offset is not None:
            return self.exam_datetime.replace(
                tzinfo=timezone(parse_tz_offset(self.exam_tz_offset))
            )
        return self.exam_datetime.replace(tzinfo=default_tz)

    @property
    def driver_full_name(self) -> str:
        """ФИО водителя полностью."""
        parts = (self.driver_last_name, self.driver_first_name, self.driver_middle_name)
        return " ".join(p for p in parts if p)

    @property
    def specialist_full_name(self) -> str:
        """ФИО специалиста полностью."""
        parts = (
            self.specialist_last_name,
            self.specialist_first_name,
            self.specialist_middle_name,
        )
        return " ".join(p for p in parts if p)

    @property
    def license_text(self) -> str | None:
        """Права водителя одной строкой (как пришли, без разбора на серию и номер)."""
        if self.driver_license:
            return self.driver_license
        parts = (self.driver_license_series, self.driver_license_number)
        return " ".join(p for p in parts if p) or None


_ = HarmfulFactors  # используется в сервисе приёма при сопоставлении признака вредных факторов

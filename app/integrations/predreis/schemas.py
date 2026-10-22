"""Контракт входящих событий Предрейс → журналы (черновик, см. docs/integration-contract.md)."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.enums import (
    ContractType,
    Gender,
    Role,
    WorkFormat,
)


class OrganizationPayload(BaseModel):
    """Организация."""

    id: uuid.UUID
    inn: str
    legal_form: str | None = None
    name: str
    short_name: str | None = None
    kpp: str | None = None
    ogrn: str | None = None
    legal_address: str | None = None
    head_name: str | None = None
    email: str | None = None
    phone: str | None = None
    contract_type: ContractType | None = None
    contract_number: str | None = None
    contract_date: date | None = None
    contract_until: date | None = None
    work_format: WorkFormat
    is_active: bool = True
    note: str | None = None


class DriverPayload(BaseModel):
    """Водитель. Пол (gender) — новое поле, которое нужно добавить в Предрейс."""

    id: uuid.UUID
    organization_id: uuid.UUID
    full_name: str
    gender: Gender
    birth_date: date
    snils: str | None = None
    license_number: str | None = None
    license_issued_at: date | None = None
    license_valid_until: date | None = None
    is_active: bool = True
    note: str | None = None


class VehiclePayload(BaseModel):
    """Транспортное средство."""

    id: uuid.UUID
    organization_id: uuid.UUID
    brand: str
    model: str
    vehicle_type: str | None = None
    plate: str
    diag_card_until: date | None = None
    is_active: bool = True
    note: str | None = None


class UserPayload(BaseModel):
    """Пользователь платформы."""

    id: uuid.UUID
    role: Role
    full_name: str
    email: str | None = None
    organization_id: uuid.UUID | None = None
    journals_access: bool = False
    is_active: bool = True


class _EventBase(BaseModel):
    """Общие поля события."""

    event_id: uuid.UUID
    occurred_at: datetime


class OrganizationUpserted(_EventBase):
    """Организация создана или изменена."""

    event_type: Literal["organization.upserted"]
    organization: OrganizationPayload


class DriverUpserted(_EventBase):
    """Водитель создан или изменён."""

    event_type: Literal["driver.upserted"]
    driver: DriverPayload


class VehicleUpserted(_EventBase):
    """ТС создано или изменено."""

    event_type: Literal["vehicle.upserted"]
    vehicle: VehiclePayload


class UserUpserted(_EventBase):
    """Пользователь создан или изменён (в т.ч. включён/выключен доступ к журналам)."""

    event_type: Literal["user.upserted"]
    user: UserPayload


_OFFSET_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")

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
)
TECHNICAL_DETAIL_FIELDS = (
    "vehicle_type",
    "brakes_ok",
    "lighting_ok",
    "tires_ok",
    "released",
    "mechanic_position",
    "recorded_at",
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
    """Запись из ЭПЛ: Т2/Т6 (медосмотр), Т3 (техконтроль). Плоский формат Предрейса.

    Отправляется только после получения QR. Идентификаторы организации, водителя и ТС
    (`organization_id`, `driver_id`, `vehicle_id`) и `event_id` — дополнения к списку полей.
    """

    event_type: Literal["T2", "T3", "T6"]
    event_id: uuid.UUID
    source: Literal["epl"] = "epl"
    waybill_id: uuid.UUID
    waybill_number: str
    gis_uid: str
    qr_issued: bool

    organization_id: uuid.UUID
    driver_id: uuid.UUID
    vehicle_id: uuid.UUID | None = None
    specialist_user_id: uuid.UUID

    org_inn: str
    org_kpp: str | None = None
    org_ogrn: str | None = None
    org_name: str
    org_address: str

    driver_last_name: str
    driver_first_name: str
    driver_middle_name: str | None = None
    driver_birth_date: date
    driver_gender: Gender | None = None
    driver_license_series: str
    driver_license_number: str

    specialist_last_name: str
    specialist_first_name: str
    specialist_middle_name: str | None = None

    exam_datetime: datetime
    exam_tz_offset: str | int

    signature_serial: str
    signature_owner: str
    signature_valid_from: datetime
    signature_valid_to: datetime
    signature_b64: str | None = None
    tsp_b64: str | None = None

    notes: str | None = None

    # --- только медосмотр (Т2/Т6): epl_details.inspection.medic / medic_post ---
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

    # --- только техконтроль (Т3): inspection.mechanic + титул и рейс ---
    brakes_ok: bool | None = None
    lighting_ok: bool | None = None
    tires_ok: bool | None = None
    vehicle_plate: str | None = None
    vehicle_brand: str | None = None
    vehicle_model: str | None = None
    vehicle_type: str | None = None
    odometer: int | None = None
    released: bool | None = None
    mechanic_position: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _default_event_id(cls, data: Any) -> Any:
        """Если Предрейс не прислал event_id, он выводится детерминированно из рейса и титула."""
        if isinstance(data, dict) and not data.get("event_id"):
            key = f"epl/{data.get('waybill_id')}/{data.get('event_type')}"
            return {**data, "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, key))}
        return data

    @model_validator(mode="after")
    def _check_consistency(self) -> EplRecordEvent:
        """Проверяет QR, часовой пояс и комплектность полей для вида титула."""
        if not self.qr_issued:
            raise ValueError("Запись создаётся только после получения QR (qr_issued=true)")
        parse_tz_offset(self.exam_tz_offset)
        required: tuple[str, ...]
        if self.event_type == "T3":
            required = (
                "vehicle_id",
                "vehicle_plate",
                "vehicle_brand",
                "vehicle_model",
                "odometer",
                "approved",
            )
        else:
            required = (
                "blood_pressure_systolic",
                "blood_pressure_diastolic",
                "pulse",
                "temperature",
                "alcohol_ppm",
                "harmful_factors_detected",
                "approved",
            )
        missing = [f for f in required if getattr(self, f) is None]
        if missing:
            raise ValueError(f"Для {self.event_type} обязательны поля: {', '.join(missing)}")
        return self

    @property
    def performed_at(self) -> datetime:
        """Момент осмотра с часовым поясом (из exam_tz_offset, если время «наивное»)."""
        if self.exam_datetime.tzinfo is not None:
            return self.exam_datetime
        return self.exam_datetime.replace(tzinfo=timezone(parse_tz_offset(self.exam_tz_offset)))

    @property
    def driver_full_name(self) -> str:
        """ФИО водителя полностью."""
        return " ".join(
            p
            for p in (self.driver_last_name, self.driver_first_name, self.driver_middle_name)
            if p
        )

    @property
    def specialist_full_name(self) -> str:
        """ФИО специалиста полностью."""
        return " ".join(
            p
            for p in (
                self.specialist_last_name,
                self.specialist_first_name,
                self.specialist_middle_name,
            )
            if p
        )


IntegrationEvent = Annotated[
    OrganizationUpserted | DriverUpserted | VehicleUpserted | UserUpserted | EplRecordEvent,
    Field(discriminator="event_type"),
]

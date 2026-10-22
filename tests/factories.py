"""Фабрики тестовых данных и заглушки внешних систем."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Principal
from app.domain.enums import Gender, Role, SignatureKind, WorkFormat
from app.integrations.predreis.client import SignResult
from app.integrations.predreis.schemas import (
    DriverPayload,
    OrganizationPayload,
    UserPayload,
    VehiclePayload,
)
from app.modules.catalog.service import (
    upsert_driver,
    upsert_organization,
    upsert_user,
    upsert_vehicle,
)

MSK = timezone(timedelta(hours=3))


def new_id() -> uuid.UUID:
    """Новый UUID."""
    return uuid.uuid4()


def principal(
    role: Role, user_id: uuid.UUID | None = None, org_id: uuid.UUID | None = None
) -> Principal:
    """Пользователь с включённым доступом к журналам."""
    return Principal(
        user_id=user_id or new_id(),
        role=role,
        journals_access=True,
        org_id=org_id,
        full_name=f"Тест {role.value}",
        raw_token="test-token",
    )


def org_payload(work_format: WorkFormat = WorkFormat.EPL, **kw: Any) -> OrganizationPayload:
    """Тестовая организация."""
    return OrganizationPayload(
        **{
            "id": new_id(),
            "inn": "7707083893",
            "name": "ООО «Тестовая логистика»",
            "short_name": "Тест-Логистик",
            "legal_address": "г. Москва, ул. Тестовая, 1",
            "work_format": work_format,
            **kw,
        }
    )


def driver_payload(org_id: uuid.UUID, **kw: Any) -> DriverPayload:
    """Тестовый водитель."""
    return DriverPayload(
        **{
            "id": new_id(),
            "organization_id": org_id,
            "full_name": "Ефимов Андрей Константинович",
            "gender": Gender.MALE,
            "birth_date": date(1980, 1, 1),
            **kw,
        }
    )


def vehicle_payload(org_id: uuid.UUID, **kw: Any) -> VehiclePayload:
    """Тестовое ТС."""
    return VehiclePayload(
        **{
            "id": new_id(),
            "organization_id": org_id,
            "brand": "ГАЗон",
            "model": "Next",
            "plate": "О224ЕК790",
            **kw,
        }
    )


def user_payload(role: Role, **kw: Any) -> UserPayload:
    """Тестовый пользователь платформы."""
    return UserPayload(
        **{"id": new_id(), "role": role, "full_name": f"{role.value.title()} Тестов", **kw}
    )


class World:
    """Набор связанных сущностей для сценариев."""

    org: OrganizationPayload
    driver: DriverPayload
    vehicle: VehiclePayload
    medic: UserPayload
    mechanic: UserPayload
    manager: UserPayload


async def seed(session: AsyncSession, work_format: WorkFormat = WorkFormat.EPL) -> World:
    """Создаёт организацию, водителя, ТС, медика, механика и менеджера в реплике."""
    w = World()
    w.org = org_payload(work_format)
    await upsert_organization(session, w.org)
    w.driver = driver_payload(w.org.id)
    w.vehicle = vehicle_payload(w.org.id)
    w.medic = user_payload(Role.MEDIC, journals_access=True)
    w.mechanic = user_payload(Role.MECHANIC)
    w.manager = user_payload(Role.PREDREIS)
    await upsert_driver(session, w.driver)
    await upsert_vehicle(session, w.vehicle)
    for u in (w.medic, w.mechanic, w.manager):
        await upsert_user(session, u)
    await session.commit()
    return w


class FakeSigner:
    """Заглушка Предрейса: возвращает фиктивную подпись и сертификат."""

    def __init__(self) -> None:
        """Запоминает вызовы."""
        self.calls: list[tuple[str, SignatureKind]] = []

    async def sign_detached(
        self,
        *,
        content: bytes,
        filename: str,
        kind: SignatureKind,
        signer_user_id: uuid.UUID | None,
        on_behalf_token: str | None,
    ) -> SignResult:
        """Возвращает фиктивный результат подписи."""
        self.calls.append((filename, kind))
        now = datetime.now(timezone.utc)
        return SignResult(
            signature=b"SIG:" + content[:16],
            tsp=b"TSP",
            cert_serial="f18dd73747eccc4ab0d2b1ee00d4040e",
            cert_subject=(
                "ООО «ПРЕДРЕЙС»"
                if kind is SignatureKind.ORGANIZATION
                else "Абдуллаева Гульзана Абутдиновна"
            ),
            cert_valid_from=now - timedelta(days=365),
            cert_valid_to=now + timedelta(days=365),
            ocsp_status="good",
            signed_at=now,
        )


EXAM = datetime(2026, 10, 14, 8, 20)


def epl_event(event_type: str = "T2", w: World | None = None, **over: Any) -> dict[str, Any]:
    """Валидное ЭПЛ-событие в плоском формате Предрейса (T2/T6 — медосмотр, T3 — техконтроль)."""
    org_id = w.org.id if w else new_id()
    base: dict[str, Any] = {
        "event_type": event_type,
        "event_id": str(new_id()),
        "source": "epl",
        "waybill_id": str(new_id()),
        "waybill_number": "ЭПЛ-2026-000123",
        "gis_uid": "7f1c1f0a-0000-4000-8000-000000000001",
        "qr_issued": True,
        "organization_id": str(org_id),
        "driver_id": str(w.driver.id if w else new_id()),
        "vehicle_id": str(w.vehicle.id if w else new_id()) if event_type == "T3" else None,
        "specialist_user_id": str(
            (w.mechanic.id if event_type == "T3" else w.medic.id) if w else new_id()
        ),
        "org_inn": "7707083893",
        "org_kpp": "770701001",
        "org_ogrn": "1027700132195",
        "org_name": "ООО «Название на момент осмотра»",
        "org_address": "г. Москва, ул. Осмотровая, 5",
        "driver_last_name": "Ефимов",
        "driver_first_name": "Андрей",
        "driver_middle_name": "Константинович",
        "driver_birth_date": "1974-07-21",
        "driver_gender": "M",
        "driver_license_series": "77 03",
        "driver_license_number": "123456",
        "specialist_last_name": "Абдуллаева",
        "specialist_first_name": "Гульзана",
        "specialist_middle_name": "Абутдиновна",
        "exam_datetime": EXAM.isoformat(),
        "exam_tz_offset": "+03:00",
        "signature_serial": "f18dd73747eccc4ab0d2b1ee00d4040e",
        "signature_owner": "Абдуллаева Гульзана Абутдиновна",
        "signature_valid_from": "2024-09-17T00:00:00+03:00",
        "signature_valid_to": "2039-06-19T00:00:00+03:00",
        "notes": None,
    }
    if event_type == "T3":
        base |= {
            "vehicle_plate": "О224ЕК790",
            "vehicle_brand": "Грузовой ГАЗон",
            "vehicle_model": "2824ЕИ",
            "vehicle_type": "грузовой",
            "odometer": 1167,
            "brakes_ok": True,
            "lighting_ok": True,
            "tires_ok": True,
            "approved": True,
            "released": True,
            "mechanic_position": "Механик",
            "recorded_at": "2026-10-14T08:36:00+03:00",
        }
    else:
        base |= {
            "blood_pressure_systolic": 137,
            "blood_pressure_diastolic": 84,
            "pulse": 72,
            "temperature": "36.6",
            "alcohol_detected": False,
            "alcohol_ppm": "0.00",
            "complaints": "отсутствуют",
            "harmful_factors_detected": False,
            "approved": True,
            "critical_flag": False,
            "recorded_at": "2026-10-14T08:20:00+03:00",
            "medic_license_series": "Л041",
            "medic_license_number": "01162",
            "medic_org_name": "ООО «ПРЕДРЕЙС»",
            "vid_mo": "предрейсовый",
            "is_pre_trip": event_type == "T2",
            "is_post_trip": event_type == "T6",
        }
    return {**base, **over}

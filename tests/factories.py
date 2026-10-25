"""Фабрики тестовых данных и заглушки внешних систем."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.core.security import Principal
from app.core.storage import Storage
from app.domain.enums import Gender, JournalKind, Role, WorkFormat
from app.integrations.predreis.client import CertInfo, SignStatus, SignTicket
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
from app.modules.ejournal.service import EJournalService
from app.modules.records.schemas import SignBatchResult
from app.modules.signing.service import SigningService

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


@dataclass
class SubmitCall:
    """Вызов отправки на подпись, записанный заглушкой."""

    document_type: str
    signer_user_id: uuid.UUID
    external_id: str
    content: bytes


class FakeSigner:
    """Заглушка шлюза подписи Предрейса: принимает задачи и подписывает при опросе."""

    def __init__(
        self,
        *,
        cert: bool = True,
        fail: str | None = None,
        hold: bool = False,
        submit_error: bool = False,
    ) -> None:
        """cert — отдавать сведения о сертификате; fail — причина отказа; hold — не подписывать."""
        self.cert, self.fail, self.hold, self.submit_error = cert, fail, hold, submit_error
        self.calls: list[SubmitCall] = []
        self._jobs: dict[str, SubmitCall] = {}

    async def submit(
        self, *, signer_user_id: uuid.UUID, document_type: str, content: bytes, external_id: str
    ) -> SignTicket:
        """Принимает документ; при submit_error имитирует недоступность Предрейса."""
        if self.submit_error:
            raise UpstreamError("Предрейс недоступен")
        call = SubmitCall(document_type, signer_user_id, external_id, content)
        self.calls.append(call)
        self._jobs[external_id] = call
        return SignTicket(sign_id=str(uuid.uuid4()), status="pending")

    async def fetch(self, external_ids: Sequence[str]) -> list[SignStatus]:
        """Отдаёт состояния: pending, failed или signed (с подписью и сертификатом)."""
        now = datetime.now(timezone.utc)
        out: list[SignStatus] = []
        for ext in external_ids:
            call = self._jobs.get(ext)
            if call is None:
                continue
            if self.hold:
                out.append(SignStatus(ext, None, "pending"))
            elif self.fail:
                out.append(SignStatus(ext, None, "failed", error=self.fail))
            else:
                org = call.document_type == get_settings().journal_sign_document_type
                cert = CertInfo(
                    "f18dd73747eccc4ab0d2b1ee00d4040e",
                    "ООО «ПРЕДРЕЙС»" if org else "Абдуллаева Гульзана Абутдиновна",
                    now - timedelta(days=365),
                    now + timedelta(days=365),
                )
                out.append(
                    SignStatus(
                        ext,
                        None,
                        "signed",
                        signature=b"SIG:" + call.content[:16],
                        tsp=b"TSP",
                        certificate=cert if self.cert else None,
                        ocsp_status="good",
                        signed_at=now,
                    )
                )
        return out


async def sign_records_now(
    session: AsyncSession,
    gateway: FakeSigner,
    storage: Storage,
    who: Principal,
    kind: JournalKind,
    ids: list[uuid.UUID],
) -> SignBatchResult:
    """Ставит записи на подпись и сразу прогоняет воркер: итог — подписанные записи."""
    svc = SigningService(session, gateway, storage)
    result = await svc.request_signing(who, kind, ids)
    await svc.process_jobs()
    return result


async def sign_journal_now(
    session: AsyncSession,
    gateway: FakeSigner,
    storage: Storage,
    ejournals: EJournalService,
    who: Principal,
    journal_id: uuid.UUID,
) -> None:
    """Подпись журнала: СА нажимает «Подписать», воркер завершает подпись."""
    await ejournals.sign(who, journal_id)
    await SigningService(session, gateway, storage, journal_finisher=ejournals).process_jobs()


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

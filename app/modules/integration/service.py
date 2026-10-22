"""Обработка входящих событий Предрейса: идемпотентно, в одной транзакции."""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationFailedError
from app.core.storage import Storage, get_storage
from app.domain.enums import (
    HarmfulFactors,
    InspectionPhase,
    InspectionResult,
    JournalKind,
    RecordSource,
    RecordStatus,
    Role,
)
from app.integrations.predreis.schemas import (
    MEDICAL_DETAIL_FIELDS,
    TECHNICAL_DETAIL_FIELDS,
    DriverUpserted,
    EplRecordEvent,
    IntegrationEvent,
    OrganizationUpserted,
    UserUpserted,
    VehicleUpserted,
)
from app.models.catalog import Driver, Organization, User, Vehicle
from app.models.documents import RecordDocument
from app.models.integration import InboxEvent
from app.models.records import MedicalRecord, TechnicalRecord
from app.modules.audit.service import append_audit
from app.modules.catalog.service import (
    upsert_driver,
    upsert_organization,
    upsert_user,
    upsert_vehicle,
)

logger = logging.getLogger(__name__)


class IntegrationService:
    """Применяет события Предрейса к реплике и журналам."""

    def __init__(self, session: AsyncSession, storage: Storage | None = None) -> None:
        """Сохраняет сессию БД и хранилище файлов."""
        self.session = session
        self.storage = storage or get_storage()

    async def handle(self, event: IntegrationEvent) -> str:
        """Обрабатывает событие; повторная доставка возвращает «duplicate» без эффектов."""
        try:
            inserted = (
                await self.session.execute(
                    pg_insert(InboxEvent)
                    .values(
                        event_id=event.event_id,
                        event_type=event.event_type,
                        payload=event.model_dump(mode="json"),
                    )
                    .on_conflict_do_nothing(index_elements=["event_id"])
                    .returning(InboxEvent.event_id)
                )
            ).scalar_one_or_none()
            if inserted is None:
                await self.session.rollback()
                return "duplicate"
            match event:
                case OrganizationUpserted():
                    await upsert_organization(self.session, event.organization)
                case DriverUpserted():
                    await upsert_driver(self.session, event.driver)
                case VehicleUpserted():
                    await upsert_vehicle(self.session, event.vehicle)
                case UserUpserted():
                    await upsert_user(self.session, event.user)
                case EplRecordEvent():
                    await self._handle_epl(event)
            await self.session.execute(
                update(InboxEvent)
                .where(InboxEvent.event_id == event.event_id)
                .values(processed_at=datetime.now(timezone.utc))
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            logger.warning(
                "Событие %s: зависимая сущность не синхронизирована (%s)", event.event_id, exc.orig
            )
            raise ConflictError(
                "Зависимая сущность ещё не синхронизирована, повторите позже",
                code="dependency_missing",
            ) from exc
        return "processed"

    async def _resolve_epl_refs(
        self, ev: EplRecordEvent
    ) -> tuple[Organization, Driver, Vehicle | None, User]:
        """Находит реплики по идентификаторам; нет реплики — просим Предрейс повторить позже."""
        org = await self.session.get(Organization, ev.organization_id)
        driver = await self.session.get(Driver, ev.driver_id)
        vehicle = await self.session.get(Vehicle, ev.vehicle_id) if ev.vehicle_id else None
        specialist = await self.session.get(User, ev.specialist_user_id)
        missing = [
            name
            for name, obj, needed in (
                ("organization", org, True),
                ("driver", driver, True),
                ("vehicle", vehicle, ev.event_type == "T3"),
                ("specialist", specialist, True),
            )
            if needed and obj is None
        ]
        if missing:
            raise ConflictError(
                f"Не синхронизированы справочники: {', '.join(missing)}", code="dependency_missing"
            )
        assert org is not None and driver is not None and specialist is not None
        if driver.organization_id != org.id:
            raise ValidationFailedError("Водитель не принадлежит организации события")
        expected = Role.MECHANIC if ev.event_type == "T3" else Role.MEDIC
        if specialist.role is not expected:
            raise ValidationFailedError(
                f"Для {ev.event_type} специалист должен иметь роль {expected.value}",
                code="specialist_role_mismatch",
            )
        return org, driver, vehicle, specialist

    @staticmethod
    def _epl_snapshot(ev: EplRecordEvent) -> dict[str, Any]:
        """Снимок реквизитов строится из события (данные на момент осмотра), а не из реплики."""
        snap: dict[str, Any] = {
            "organization": {
                "inn": ev.org_inn,
                "kpp": ev.org_kpp,
                "ogrn": ev.org_ogrn,
                "name": ev.org_name,
                "short_name": None,
                "legal_address": ev.org_address,
            },
            "driver": {
                "full_name": ev.driver_full_name,
                "birth_date": ev.driver_birth_date.isoformat(),
                "gender": ev.driver_gender.value if ev.driver_gender else None,
                "license": f"{ev.driver_license_series} {ev.driver_license_number}",
            },
            "specialist": {"full_name": ev.specialist_full_name},
        }
        if ev.event_type == "T3":
            snap["vehicle"] = {
                "brand": ev.vehicle_brand,
                "model": ev.vehicle_model,
                "vehicle_type": ev.vehicle_type,
                "plate": ev.vehicle_plate,
            }
        return snap

    async def _handle_epl(self, ev: EplRecordEvent) -> None:
        """Создаёт запись типа Б из ЭПЛ (Т2/Т6 → медосмотр, Т3 → техконтроль)."""
        org, driver, vehicle, specialist = await self._resolve_epl_refs(ev)
        is_technical = ev.event_type == "T3"
        details_fields = TECHNICAL_DETAIL_FIELDS if is_technical else MEDICAL_DETAIL_FIELDS
        common: dict[str, Any] = {
            "status": RecordStatus.SIGNED,
            "source": RecordSource.EPL,
            "epl_waybill_id": ev.waybill_id,
            "epl_title_number": int(ev.event_type[1:]),
            "gis_uid": ev.gis_uid,
            "waybill_number": ev.waybill_number,
            "organization_id": org.id,
            "specialist_user_id": specialist.id,
            "performed_at": ev.performed_at,
            "snapshot": self._epl_snapshot(ev),
            "note": (ev.notes or "").strip() or None,
            "epl_details": ev.model_dump(
                mode="json", include=set(details_fields), exclude_none=True
            ),
        }
        result = InspectionResult.ADMITTED if ev.approved else InspectionResult.NOT_ADMITTED
        model: type[MedicalRecord] | type[TechnicalRecord]
        if is_technical:
            assert vehicle is not None and ev.odometer is not None
            kind = JournalKind.TECHNICAL
            model = TechnicalRecord
            values = {
                **common,
                "vehicle_id": vehicle.id,
                "driver_id": driver.id,
                "odometer": ev.odometer,
                "result": result,
            }
        else:
            assert ev.temperature is not None and ev.alcohol_ppm is not None
            assert (
                ev.blood_pressure_systolic is not None and ev.blood_pressure_diastolic is not None
            )
            assert ev.pulse is not None
            kind = JournalKind.MEDICAL
            model = MedicalRecord
            if isinstance(ev.harmful_factors, list):
                factors_note = ", ".join(ev.harmful_factors) or None
            else:
                factors_note = ev.harmful_factors or None
            values = {
                **common,
                "phase": InspectionPhase.PRE if ev.event_type == "T2" else InspectionPhase.POST,
                "driver_id": driver.id,
                "complaints": ev.complaints or "отсутствуют",
                "bp_systolic": ev.blood_pressure_systolic,
                "bp_diastolic": ev.blood_pressure_diastolic,
                "pulse": ev.pulse,
                "temperature": ev.temperature,
                # ЭПЛ присылает ppm; единицы (mg/L или ‰) уточняются, значение хранится как есть.
                "alcohol_mgl": ev.alcohol_ppm,
                "harmful_factors": (
                    HarmfulFactors.DETECTED
                    if ev.harmful_factors_detected
                    else HarmfulFactors.ABSENT
                ),
                "harmful_factors_note": factors_note,
                "result": result,
            }
        record_id = (
            await self.session.execute(
                pg_insert(model)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["epl_waybill_id", "epl_title_number"])
                .returning(model.id)
            )
        ).scalar_one_or_none()
        if record_id is None:
            logger.info("Запись ЭПЛ %s/%s уже импортирована", ev.waybill_id, ev.event_type)
            return
        base = f"records/{kind.value}/{record_id}"
        sig_key = (
            await self.storage.put(f"{base}/epl.sig", base64.b64decode(ev.signature_b64))
            if ev.signature_b64
            else None
        )
        tsp_key = (
            await self.storage.put(f"{base}/epl.tsp", base64.b64decode(ev.tsp_b64))
            if ev.tsp_b64
            else None
        )
        self.session.add(
            RecordDocument(
                record_kind=kind,
                record_id=record_id,
                sig_key=sig_key,
                tsp_key=tsp_key,
                signer_user_id=specialist.id,
                cert_serial=ev.signature_serial,
                cert_subject=ev.signature_owner,
                cert_valid_from=ev.signature_valid_from,
                cert_valid_to=ev.signature_valid_to,
                signed_at=ev.recorded_at,
            )
        )
        await self.session.flush()
        await append_audit(
            self.session,
            None,
            action="record.import_epl",
            entity_type=kind.value,
            entity_id=str(record_id),
            payload={
                "waybill_id": str(ev.waybill_id),
                "title": ev.event_type,
                "gis_uid": ev.gis_uid,
            },
        )

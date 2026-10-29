"""Приём ЭПЛ-событий из очереди Предрейса: идемпотентно, в одной транзакции."""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import ConflictError, ValidationFailedError
from app.core.storage import Storage, get_storage
from app.core.timeutils import business_tz, local_date
from app.domain.contracts import CONTRACT_EXCLUDES_MESSAGE, journal_allowed
from app.domain.enums import (
    HarmfulFactors,
    InspectionPhase,
    InspectionResult,
    JournalKind,
    RecordSource,
    RecordStatus,
    Role,
)
from app.domain.validators import normalize_plate
from app.integrations.predreis.cms import extract_cert_info
from app.integrations.predreis.schemas import (
    MEDICAL_DETAIL_FIELDS,
    TECHNICAL_DETAIL_FIELDS,
    EplRecordEvent,
)
from app.models.catalog import Driver, Organization, User, Vehicle
from app.models.documents import RecordDocument
from app.models.integration import InboxEvent
from app.models.records import MedicalRecord, TechnicalRecord
from app.modules.audit.service import append_audit
from app.modules.catalog.service import upsert_specialist

logger = logging.getLogger(__name__)


def _plate(value: str) -> str:
    """Госномер для сравнения (единое правило с каталогом)."""
    return normalize_plate(value)


class IntegrationService:
    """Применяет ЭПЛ-события к журналам."""

    def __init__(
        self,
        session: AsyncSession,
        storage: Storage | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Сохраняет сессию БД, хранилище файлов и настройки."""
        self.session = session
        self.storage = storage or get_storage()
        self.settings = settings or get_settings()

    async def handle(self, event: EplRecordEvent) -> str:
        """Обрабатывает событие: processed, duplicate или skipped (осмотр до даты запуска)."""
        performed_at = event.performed_at(business_tz())
        try:
            inserted = (
                await self.session.execute(
                    pg_insert(InboxEvent)
                    .values(
                        event_id=event.event_id,
                        event_type=event.event_type,
                        payload=event.model_dump(
                            mode="json", exclude={"signature_b64", "tsp_b64"}
                        ),
                    )
                    .on_conflict_do_nothing(index_elements=["event_id"])
                    .returning(InboxEvent.event_id)
                )
            ).scalar_one_or_none()
            if inserted is None:
                await self.session.rollback()
                return "duplicate"
            cutoff = self.settings.epl_import_from
            outcome = "processed"
            if cutoff is not None and local_date(performed_at) < cutoff:
                outcome = "skipped"
            else:
                await self._handle_epl(event, performed_at)
            await self.session.execute(
                update(InboxEvent)
                .where(InboxEvent.event_id == event.event_id)
                .values(processed_at=datetime.now(timezone.utc))
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            logger.warning("Событие %s: нарушение целостности (%s)", event.event_id, exc.orig)
            raise ConflictError(
                "Зависимая сущность ещё не синхронизирована, повторите позже",
                code="dependency_missing",
            ) from exc
        return outcome

    # --- привязка к справочникам -------------------------------------------------------------
    async def _by_predreis_id(self, model: Any, predreis_id: uuid.UUID) -> Any:
        """Карточка по идентификатору Предрейса (у объединённой карточки наш id другой)."""
        return (
            await self.session.execute(select(model).where(model.predreis_id == predreis_id))
        ).scalar_one_or_none()

    async def _find_org(self, ev: EplRecordEvent) -> Organization:
        """Организация по идентификатору либо по ИНН (и КПП, если с таким ИНН их несколько)."""
        if ev.organization_id:
            org = await self._by_predreis_id(Organization, ev.organization_id)
            if org is not None:
                return org
        found = (
            (
                await self.session.execute(
                    select(Organization).where(Organization.inn == ev.org_inn)
                )
            )
            .scalars()
            .all()
        )
        if len(found) > 1 and ev.org_kpp:
            found = [o for o in found if o.kpp == ev.org_kpp]
        if len(found) == 1:
            return found[0]
        if not found:
            raise ConflictError(
                "Не синхронизирована организация события", code="dependency_missing"
            )
        raise ConflictError(
            "Организацию события нельзя определить однозначно", code="ambiguous_org"
        )

    async def _find_driver(self, ev: EplRecordEvent, org: Organization) -> Driver:
        """Водитель по идентификатору либо по ФИО и дате рождения в организации."""
        if ev.driver_id:
            driver = await self._by_predreis_id(Driver, ev.driver_id)
            if driver is not None:
                return driver
        found = (
            (
                await self.session.execute(
                    select(Driver).where(
                        Driver.organization_id == org.id,
                        func.lower(Driver.full_name) == ev.driver_full_name.lower(),
                        Driver.birth_date == ev.driver_birth_date,
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(found) == 1:
            return found[0]
        if not found:
            raise ConflictError("Не синхронизирован водитель события", code="dependency_missing")
        raise ConflictError(
            "Водителя события нельзя определить однозначно", code="ambiguous_driver"
        )

    async def _find_vehicle(self, ev: EplRecordEvent, org: Organization) -> Vehicle:
        """ТС по идентификатору либо по госномеру в организации."""
        if ev.vehicle_id:
            vehicle = await self._by_predreis_id(Vehicle, ev.vehicle_id)
            if vehicle is not None:
                return vehicle
        wanted = _plate(ev.vehicle_plate or "")
        rows = (
            (await self.session.execute(select(Vehicle).where(Vehicle.organization_id == org.id)))
            .scalars()
            .all()
        )
        found = [v for v in rows if _plate(v.plate) == wanted]
        if len(found) == 1:
            return found[0]
        if not found:
            raise ConflictError("Не синхронизировано ТС события", code="dependency_missing")
        raise ConflictError("ТС события нельзя определить однозначно", code="ambiguous_vehicle")

    @staticmethod
    def _epl_snapshot(ev: EplRecordEvent) -> dict[str, Any]:
        """Снимок реквизитов строится из события (данные на момент осмотра), а не из реплики."""
        snap: dict[str, Any] = {
            "organization": {
                "inn": ev.org_inn,
                "kpp": ev.org_kpp,
                "ogrn": ev.org_ogrn,
                "name": ev.org_name,
                "short_name": ev.org_short_name,
                "legal_address": ev.org_address,
            },
            "driver": {
                "full_name": ev.driver_full_name,
                "birth_date": ev.driver_birth_date.isoformat(),
                "gender": ev.driver_gender.value if ev.driver_gender else None,
                "license": ev.license_text,
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

    async def _handle_epl(self, ev: EplRecordEvent, performed_at: datetime) -> None:
        """Создаёт запись типа Б из ЭПЛ (Т2/Т6 → медосмотр, Т3 → техконтроль)."""
        is_technical = ev.event_type == "T3"
        org = await self._find_org(ev)
        kind = JournalKind.TECHNICAL if is_technical else JournalKind.MEDICAL
        if not journal_allowed(org.contract_type, kind):
            raise ValidationFailedError(
                CONTRACT_EXCLUDES_MESSAGE[kind], code="contract_excludes_journal"
            )
        driver = await self._find_driver(ev, org)
        if driver.organization_id != org.id:
            raise ValidationFailedError("Водитель не принадлежит организации события")
        vehicle = await self._find_vehicle(ev, org) if is_technical else None
        role = Role.MECHANIC if is_technical else Role.MEDIC
        await upsert_specialist(self.session, ev.specialist_user_id, role, ev.specialist_full_name)
        specialist = await self.session.get(User, ev.specialist_user_id, populate_existing=True)
        if not (specialist is not None):  # явная проверка: assert исчезает при python -O
            raise RuntimeError("Нарушено внутреннее условие")
        if specialist.role is not role:
            raise ValidationFailedError(
                f"Для {ev.event_type} специалист должен иметь роль {role.value}",
                code="specialist_role_mismatch",
            )

        details_fields = TECHNICAL_DETAIL_FIELDS if is_technical else MEDICAL_DETAIL_FIELDS
        details = ev.model_dump(mode="json", include=set(details_fields), exclude_none=True)
        if ev.signature_state:
            details["signature_state"] = ev.signature_state
        common: dict[str, Any] = {
            "status": RecordStatus.SIGNED,
            "source": RecordSource.EPL,
            "epl_waybill_id": ev.waybill_id,
            "epl_title_number": int(ev.event_type[1:]),
            "gis_uid": ev.gis_uid,
            "waybill_number": ev.waybill_number,
            "organization_id": org.id,
            "specialist_user_id": specialist.id,
            "performed_at": performed_at,
            "snapshot": self._epl_snapshot(ev),
            "note": (ev.notes or "").strip() or None,
            "epl_details": details,
        }
        result = InspectionResult.ADMITTED if ev.approved else InspectionResult.NOT_ADMITTED
        model: type[MedicalRecord] | type[TechnicalRecord]
        if is_technical:
            if not (
                vehicle is not None and ev.odometer is not None
            ):  # явная проверка: assert исчезает при python -O
                raise RuntimeError("Нарушено внутреннее условие")
            kind, model = JournalKind.TECHNICAL, TechnicalRecord
            values = {
                **common,
                "vehicle_id": vehicle.id,
                "driver_id": driver.id,
                "odometer": ev.odometer,
                "result": result,
            }
        else:
            if not (
                ev.temperature is not None and ev.alcohol_ppm is not None
            ):  # явная проверка: assert исчезает при python -O
                raise RuntimeError("Нарушено внутреннее условие")
            if not (
                ev.blood_pressure_systolic is not None and ev.blood_pressure_diastolic is not None
            ):  # явная проверка: assert исчезает при python -O
                raise RuntimeError("Нарушено внутреннее условие")
            if not (ev.pulse is not None):  # явная проверка: assert исчезает при python -O
                raise RuntimeError("Нарушено внутреннее условие")
            kind, model = JournalKind.MEDICAL, MedicalRecord
            factors = ev.harmful_factors
            factors_note = ", ".join(factors) if isinstance(factors, list) else (factors or None)
            values = {
                **common,
                "phase": InspectionPhase.PRE if ev.event_type == "T2" else InspectionPhase.POST,
                "driver_id": driver.id,
                "complaints": ev.complaints or "отсутствуют",
                "bp_systolic": ev.blood_pressure_systolic,
                "bp_diastolic": ev.blood_pressure_diastolic,
                "pulse": ev.pulse,
                "temperature": ev.temperature,
                # ЭПЛ присылает промилле; единицы (mg/L или ‰) уточняются, значение как есть.
                "alcohol_mgl": ev.alcohol_ppm,
                # None: признак не определялся («Водитель+»), это не то же, что «отсутствуют».
                "harmful_factors": (
                    None
                    if ev.harmful_factors_detected is None
                    else (
                        HarmfulFactors.DETECTED
                        if ev.harmful_factors_detected
                        else HarmfulFactors.ABSENT
                    )
                ),
                "harmful_factors_note": factors_note or None,
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
        await self._store_document(ev, kind, record_id, specialist.id)
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

    async def _store_document(
        self, ev: EplRecordEvent, kind: JournalKind, record_id: Any, specialist_id: Any
    ) -> None:
        """Сохраняет сведения о подписи титула (из события или из переданной подписи)."""
        base = f"records/{kind.value}/{record_id}"
        signature = base64.b64decode(ev.signature_b64) if ev.signature_b64 else None
        sig_key = await self.storage.put(f"{base}/epl.sig", signature) if signature else None
        tsp_key = (
            await self.storage.put(f"{base}/epl.tsp", base64.b64decode(ev.tsp_b64))
            if ev.tsp_b64
            else None
        )
        cert = extract_cert_info(signature) if signature else None
        self.session.add(
            RecordDocument(
                record_kind=kind,
                record_id=record_id,
                sig_key=sig_key,
                tsp_key=tsp_key,
                signer_user_id=specialist_id,
                cert_serial=ev.signature_serial or (cert.serial if cert else None),
                cert_subject=ev.signature_owner or (cert.subject if cert else None),
                cert_valid_from=ev.signature_valid_from or (cert.valid_from if cert else None),
                cert_valid_to=ev.signature_valid_to or (cert.valid_to if cert else None),
                signed_at=ev.recorded_at,
            )
        )
        await self.session.flush()

"""Сервис журнала технического контроля."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.core.security import Principal
from app.domain import fsm
from app.domain.enums import JournalKind, RecordSource, RecordStatus, Role
from app.domain.validators import merge_auto_note, odometer_issues
from app.models.catalog import Driver, User
from app.models.documents import RecordDocument
from app.models.records import TechnicalRecord
from app.modules.audit.service import append_audit
from app.modules.records.base import AnyRecord, BaseRecordService, contains_pattern
from app.modules.records.schemas import Page, PageParams, TechnicalFilters
from app.modules.records.snapshot import build_snapshot
from app.modules.technical.schemas import (
    TechnicalRecordCreate,
    TechnicalRecordOut,
    TechnicalRecordUpdate,
)


class TechnicalService(BaseRecordService):
    """Операции над записями журнала техконтроля."""

    kind = JournalKind.TECHNICAL
    model = TechnicalRecord
    specialist_role = Role.MECHANIC

    def build_out(
        self, principal: Principal, record: TechnicalRecord, doc: RecordDocument | None
    ) -> TechnicalRecordOut:
        """Формирует ответ API (поля техконтроля врачебной тайны не содержат)."""
        return TechnicalRecordOut(
            id=record.id,
            status=record.status,
            source=record.source,
            waybill_kind=record.waybill_kind,
            organization_id=record.organization_id,
            vehicle_id=record.vehicle_id,
            driver_id=record.driver_id,
            specialist_user_id=record.specialist_user_id,
            performed_at=record.performed_at,
            snapshot=record.snapshot,
            odometer=record.odometer,
            result=record.result,
            note=record.note,
            has_note=bool(record.note),
            deletion_pending=record.deletion_pending,
            in_journal_reserved=record.reserved_journal_id is not None,
            signature=self.signature_info(doc),
            actions=self.actions(record, principal),
        )

    async def out(self, principal: Principal, record: AnyRecord) -> TechnicalRecordOut:
        """Формирует ответ API для одной записи (с подгрузкой подписи)."""
        assert isinstance(record, TechnicalRecord)
        docs = await self.signatures([record.id])
        return self.build_out(principal, record, docs.get(record.id))

    async def get_out(self, principal: Principal, record_id: uuid.UUID) -> TechnicalRecordOut:
        """Возвращает одну запись в виде ответа API."""
        return await self.out(principal, await self.get(principal, record_id))

    async def clear_note_out(
        self, principal: Principal, record_id: uuid.UUID
    ) -> TechnicalRecordOut:
        """Снимает примечание и возвращает обновлённую запись."""
        return await self.out(principal, await self.clear_note(principal, record_id))

    async def list_records(
        self, principal: Principal, f: TechnicalFilters, params: PageParams
    ) -> Page[TechnicalRecordOut]:
        """Возвращает страницу архива: сначала самые новые."""
        self._ensure_view(principal)
        stmt: Any = await self._scope(select(TechnicalRecord), principal)
        stmt = self._apply_common_filters(stmt, f)
        if f.plate:
            stmt = stmt.where(
                TechnicalRecord.snapshot["vehicle"]["plate"].astext.ilike(
                    contains_pattern(f.plate), escape="\\"
                )
            )
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(TechnicalRecord.performed_at.desc(), TechnicalRecord.id.desc())
                    .offset(params.offset)
                    .limit(params.page_size)
                )
            )
            .scalars()
            .all()
        )
        docs = await self.signatures([r.id for r in rows])
        items = [self.build_out(principal, r, docs.get(r.id)) for r in rows]
        return Page[TechnicalRecordOut](
            items=items, total=total, page=params.page, page_size=params.page_size
        )

    async def _odometer_issues(
        self,
        vehicle_id: uuid.UUID,
        performed_at: datetime,
        odometer: int,
        exclude_id: uuid.UUID | None = None,
    ) -> list[str]:
        """Проверяет нарастающую последовательность показаний одометра по ТС."""
        base = select(TechnicalRecord.odometer).where(TechnicalRecord.vehicle_id == vehicle_id)
        if exclude_id:
            base = base.where(TechnicalRecord.id != exclude_id)
        previous = (
            await self.session.execute(
                base.where(TechnicalRecord.performed_at < performed_at)
                .order_by(TechnicalRecord.performed_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        following = (
            await self.session.execute(
                base.where(TechnicalRecord.performed_at > performed_at)
                .order_by(TechnicalRecord.performed_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return odometer_issues(previous, odometer, following)

    async def _optional_driver(
        self, driver_id: uuid.UUID | None, organization_id: uuid.UUID
    ) -> Driver | None:
        """Возвращает водителя, если он указан."""
        return await self._get_driver(driver_id, organization_id) if driver_id else None

    async def create(
        self,
        principal: Principal,
        data: TechnicalRecordCreate,
        *,
        source: RecordSource = RecordSource.MANUAL,
    ) -> TechnicalRecordOut:
        """Создаёт неподписанную запись техконтроля (тип А) со снимком реквизитов."""
        self._require(principal, self.perms.create)
        org = await self._get_org(data.organization_id)
        vehicle = await self._get_vehicle(data.vehicle_id, org.id)
        driver = await self._optional_driver(data.driver_id, org.id)
        specialist = await self._resolve_specialist(principal, data.specialist_user_id)
        issues = await self._odometer_issues(vehicle.id, data.performed_at, data.odometer)
        record = TechnicalRecord(
            status=RecordStatus.UNSIGNED,
            source=source,
            organization_id=org.id,
            vehicle_id=vehicle.id,
            driver_id=driver.id if driver else None,
            specialist_user_id=specialist.id,
            performed_at=data.performed_at,
            snapshot=build_snapshot(
                organization=org, specialist=specialist, driver=driver, vehicle=vehicle
            ),
            odometer=data.odometer,
            result=data.result,
            note=merge_auto_note(data.note, issues),
            created_by=principal.user_id,
        )
        self.session.add(record)
        await self.session.flush()
        await append_audit(
            self.session,
            principal,
            action="record.create",
            entity_type=self.kind.value,
            entity_id=str(record.id),
            payload={"source": source.value},
        )
        await self.session.commit()
        return self.build_out(principal, record, None)

    async def update(
        self, principal: Principal, record_id: uuid.UUID, data: TechnicalRecordUpdate
    ) -> TechnicalRecordOut:
        """Изменяет неподписанную запись; снимок реквизитов пересобирается при смене ссылок."""
        self._require(principal, self.perms.edit)
        record = await self.get(principal, record_id, for_update=True)
        assert isinstance(record, TechnicalRecord)
        fsm.ensure_editable(record.status, record.source)
        changes = data.model_dump(exclude_unset=True)
        specialist_requested = "specialist_user_id" in changes
        requested_specialist = changes.pop("specialist_user_id", None)
        nullable = {"note", "driver_id"}
        changes = {k: v for k, v in changes.items() if v is not None or k in nullable}
        for field, value in changes.items():
            setattr(record, field, value)
        if specialist_requested:
            record.specialist_user_id = (
                await self._resolve_specialist(principal, requested_specialist)
            ).id
        refs_changed = specialist_requested or bool(
            {"organization_id", "vehicle_id", "driver_id"} & changes.keys()
        )
        if refs_changed or {"performed_at", "odometer"} & changes.keys():
            org = await self._get_org(record.organization_id)
            vehicle = await self._get_vehicle(record.vehicle_id, org.id)
            if refs_changed:
                driver = await self._optional_driver(record.driver_id, org.id)
                specialist = await self.session.get(User, record.specialist_user_id)
                assert specialist is not None
                record.snapshot = build_snapshot(
                    organization=org, specialist=specialist, driver=driver, vehicle=vehicle
                )
            issues = await self._odometer_issues(
                vehicle.id, record.performed_at, record.odometer, exclude_id=record.id
            )
            record.note = merge_auto_note(record.note, issues)
        await append_audit(
            self.session,
            principal,
            action="record.update",
            entity_type=self.kind.value,
            entity_id=str(record_id),
            payload={"fields": sorted(changes.keys())},
        )
        await self.session.commit()
        return await self.out(principal, record)

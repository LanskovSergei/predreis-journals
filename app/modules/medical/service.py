"""Сервис журнала медицинских осмотров."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.core.security import Principal
from app.core.timeutils import local_date
from app.domain import fsm
from app.domain.enums import (
    Gender,
    JournalKind,
    RecordSource,
    RecordStatus,
    Role,
)
from app.domain.permissions import CLIENT_ROLES
from app.domain.validators import birth_date_issue, merge_auto_note
from app.models.catalog import User
from app.models.documents import RecordDocument
from app.models.records import MedicalRecord
from app.modules.audit.service import append_audit
from app.modules.medical.schemas import (
    MedicalRecordClientOut,
    MedicalRecordCreate,
    MedicalRecordOut,
    MedicalRecordUpdate,
)
from app.modules.records.base import AnyRecord, BaseRecordService, contains_pattern
from app.modules.records.schemas import MedicalFilters, Page, PageParams
from app.modules.records.snapshot import build_snapshot

MedicalOut = MedicalRecordOut | MedicalRecordClientOut


class MedicalService(BaseRecordService):
    """Операции над записями журнала медосмотров."""

    kind = JournalKind.MEDICAL
    model = MedicalRecord
    specialist_role = Role.MEDIC

    def build_out(
        self, principal: Principal, record: MedicalRecord, doc: RecordDocument | None
    ) -> MedicalOut:
        """Формирует ответ API: для клиента — без медицинских показателей."""
        signature = self.signature_info(doc)
        if principal.role in CLIENT_ROLES:
            driver = record.snapshot.get("driver", {})
            birth = driver.get("birth_date")
            gender = driver.get("gender")
            return MedicalRecordClientOut(
                id=record.id,
                status=record.status,
                source=record.source,
                waybill_kind=record.waybill_kind,
                phase=record.phase,
                performed_at=record.performed_at,
                driver_full_name=driver.get("full_name", ""),
                driver_birth_date=date.fromisoformat(birth) if birth else None,
                driver_gender=Gender(gender) if gender else None,
                specialist_name=record.snapshot.get("specialist", {}).get("full_name"),
                result=record.result,
                signature=signature,
            )
        return MedicalRecordOut(
            id=record.id,
            status=record.status,
            source=record.source,
            waybill_kind=record.waybill_kind,
            phase=record.phase,
            organization_id=record.organization_id,
            driver_id=record.driver_id,
            specialist_user_id=record.specialist_user_id,
            performed_at=record.performed_at,
            snapshot=record.snapshot,
            complaints=record.complaints,
            bp_systolic=record.bp_systolic,
            bp_diastolic=record.bp_diastolic,
            pulse=record.pulse,
            temperature=record.temperature,
            alcohol_mgl=record.alcohol_mgl,
            harmful_factors=record.harmful_factors,
            harmful_factors_note=record.harmful_factors_note,
            result=record.result,
            note=record.note,
            has_note=bool(record.note),
            deletion_pending=record.deletion_pending,
            in_journal_reserved=record.reserved_journal_id is not None,
            signature=signature,
            actions=self.actions(record, principal),
        )

    async def out(self, principal: Principal, record: AnyRecord) -> MedicalOut:
        """Формирует ответ API для одной записи (с подгрузкой подписи)."""
        assert isinstance(record, MedicalRecord)
        docs = await self.signatures([record.id])
        return self.build_out(principal, record, docs.get(record.id))

    async def get_out(self, principal: Principal, record_id: uuid.UUID) -> MedicalOut:
        """Возвращает одну запись в виде ответа API."""
        return await self.out(principal, await self.get(principal, record_id))

    async def clear_note_out(self, principal: Principal, record_id: uuid.UUID) -> MedicalOut:
        """Снимает примечание и возвращает обновлённую запись."""
        return await self.out(principal, await self.clear_note(principal, record_id))

    async def list_records(
        self, principal: Principal, f: MedicalFilters, params: PageParams
    ) -> Page[MedicalOut]:
        """Возвращает страницу архива: сначала самые новые."""
        self._ensure_view(principal)
        stmt: Any = await self._scope(select(MedicalRecord), principal)
        stmt = self._apply_common_filters(stmt, f)
        if f.driver_name:
            stmt = stmt.where(
                MedicalRecord.snapshot["driver"]["full_name"].astext.ilike(
                    contains_pattern(f.driver_name), escape="\\"
                )
            )
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(MedicalRecord.performed_at.desc(), MedicalRecord.id.desc())
                    .offset(params.offset)
                    .limit(params.page_size)
                )
            )
            .scalars()
            .all()
        )
        docs = await self.signatures([r.id for r in rows])
        items = [self.build_out(principal, r, docs.get(r.id)) for r in rows]
        return Page[MedicalOut](
            items=items, total=total, page=params.page, page_size=params.page_size
        )

    async def create(
        self,
        principal: Principal,
        data: MedicalRecordCreate,
        *,
        source: RecordSource = RecordSource.MANUAL,
    ) -> MedicalOut:
        """Создаёт неподписанную запись (тип А) со снимком реквизитов."""
        self._require(principal, self.perms.create)
        org = await self._get_org(data.organization_id)
        driver = await self._get_driver(data.driver_id, org.id)
        specialist = await self._resolve_specialist(principal, data.specialist_user_id)
        issue = birth_date_issue(driver.birth_date, local_date(data.performed_at))
        record = MedicalRecord(
            status=RecordStatus.UNSIGNED,
            source=source,
            phase=data.phase,
            organization_id=org.id,
            driver_id=driver.id,
            specialist_user_id=specialist.id,
            performed_at=data.performed_at,
            snapshot=build_snapshot(organization=org, specialist=specialist, driver=driver),
            complaints=data.complaints,
            bp_systolic=data.bp_systolic,
            bp_diastolic=data.bp_diastolic,
            pulse=data.pulse,
            temperature=data.temperature,
            alcohol_mgl=data.alcohol_mgl,
            harmful_factors=data.harmful_factors,
            harmful_factors_note=data.harmful_factors_note,
            result=data.result,
            note=merge_auto_note(data.note, [issue] if issue else []),
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
        self, principal: Principal, record_id: uuid.UUID, data: MedicalRecordUpdate
    ) -> MedicalOut:
        """Изменяет неподписанную запись; снимок реквизитов пересобирается при смене ссылок."""
        self._require(principal, self.perms.edit)
        record = await self.get(principal, record_id, for_update=True)
        assert isinstance(record, MedicalRecord)
        fsm.ensure_editable(record.status, record.source)
        changes = data.model_dump(exclude_unset=True)
        specialist_requested = "specialist_user_id" in changes
        requested_specialist = changes.pop("specialist_user_id", None)
        nullable = {"note", "harmful_factors_note"}
        changes = {k: v for k, v in changes.items() if v is not None or k in nullable}
        for field, value in changes.items():
            setattr(record, field, value)
        if specialist_requested:
            record.specialist_user_id = (
                await self._resolve_specialist(principal, requested_specialist)
            ).id
        refs_changed = specialist_requested or bool(
            {"organization_id", "driver_id"} & changes.keys()
        )
        if refs_changed or "performed_at" in changes:
            org = await self._get_org(record.organization_id)
            driver = await self._get_driver(record.driver_id, org.id)
            if refs_changed:
                specialist = await self.session.get(User, record.specialist_user_id)
                assert specialist is not None
                record.snapshot = build_snapshot(
                    organization=org, specialist=specialist, driver=driver
                )
            issue = birth_date_issue(driver.birth_date, local_date(record.performed_at))
            record.note = merge_auto_note(record.note, [issue] if issue else [])
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

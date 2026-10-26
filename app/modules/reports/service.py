"""Формирование отчётных PDF (Выгрузка) и PDF отдельных записей."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.security import Principal
from app.core.timeutils import local_date
from app.domain.enums import JournalKind
from app.domain.permissions import CLIENT_ROLES
from app.models.catalog import Organization
from app.models.documents import RecordDocument
from app.models.records import MedicalRecord, TechnicalRecord
from app.modules.audit.service import append_audit
from app.modules.medical.service import MedicalService
from app.modules.records.base import BaseRecordService
from app.modules.records.schemas import RecordFilters
from app.modules.reports.layouts import build_spec
from app.modules.reports.pdf import render_pdf_async
from app.modules.reports.rows import fmt_date, medical_row, technical_row
from app.modules.technical.service import TechnicalService

MEDICAL_TITLE = (
    "Отчёт о проведённом предрейсовом (предсменном), послерейсовом (послесменном) "
    "медицинском осмотре водителей"
)
TECHNICAL_TITLE = (
    "Отчёт о проведённом предрейсовом (предсменном) контроле технического состояния "
    "транспортных средств"
)
MEDICAL_RECORD_TITLE = (
    "Электронная запись о предрейсовом (предсменном) или послерейсовом (послесменном) "
    "медицинском осмотре водителя"
)
TECHNICAL_RECORD_TITLE = (
    "Электронная запись о предрейсовом контроле технического состояния транспортного средства"
)


class ExportRequest(BaseModel):
    """Параметры выгрузки: период/организация или явный список записей."""

    organization_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    record_ids: list[uuid.UUID] | None = None


def content_disposition(filename: str) -> str:
    """Заголовок Content-Disposition с корректной кодировкой кириллицы (RFC 5987)."""
    return f"attachment; filename=\"report.pdf\"; filename*=UTF-8''{quote(filename)}"


async def render_single_record_pdf(
    kind: JournalKind, record: MedicalRecord | TechnicalRecord, doc: RecordDocument | None
) -> bytes:
    """PDF одной записи (человекочитаемая часть электронного документа типа 1)."""
    org = record.snapshot.get("organization", {})
    customer = {
        "name": org.get("short_name") or org.get("name", ""),
        "inn": org.get("inn", ""),
        "address": org.get("legal_address"),
    }
    if kind is JournalKind.MEDICAL:
        assert isinstance(record, MedicalRecord)
        spec = build_spec(
            medical=True,
            title=MEDICAL_RECORD_TITLE,
            rows=[medical_row(1, record, doc)],
            customer=customer,
            settings=get_settings(),
        )
    else:
        assert isinstance(record, TechnicalRecord)
        spec = build_spec(
            medical=False,
            title=TECHNICAL_RECORD_TITLE,
            rows=[technical_row(1, record, doc)],
            customer=customer,
            settings=get_settings(),
        )
    return await render_pdf_async(spec)


JOURNAL_TITLES = {
    JournalKind.MEDICAL: (
        "Электронный журнал предрейсовых (предсменных) и послерейсовых (послесменных) "
        "медицинских осмотров водителей"
    ),
    JournalKind.TECHNICAL: (
        "Электронный журнал предрейсового контроля технического состояния транспортных средств"
    ),
}


async def render_registry_pdf(
    *,
    kind: JournalKind,
    customer: dict[str, Any],
    records: Sequence[MedicalRecord | TechnicalRecord],
    docs: dict[uuid.UUID, RecordDocument],
    period_from: str,
    period_to: str,
    title: str | None = None,
    stamp: dict[str, str] | None = None,
) -> bytes:
    """Рендерит PDF-реестр записей (Выгрузка или человекочитаемая версия электронного журнала)."""
    medical = kind is JournalKind.MEDICAL
    if medical:
        rows = [
            medical_row(i, r, docs.get(r.id))
            for i, r in enumerate(records, 1)
            if isinstance(r, MedicalRecord)
        ]
    else:
        rows = [
            technical_row(i, r, docs.get(r.id))
            for i, r in enumerate(records, 1)
            if isinstance(r, TechnicalRecord)
        ]
    spec = build_spec(
        medical=medical,
        title=title or (MEDICAL_TITLE if medical else TECHNICAL_TITLE),
        rows=rows,
        customer=customer,
        settings=get_settings(),
        period=(period_from, period_to),
        stamp=stamp,
    )
    return await render_pdf_async(spec)


class ReportService:
    """Выгрузка записей архива в PDF."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет сессию БД."""
        self.session = session

    def _service(self, kind: JournalKind) -> BaseRecordService:
        """Возвращает сервис журнала нужного вида."""
        return (
            MedicalService(self.session)
            if kind is JournalKind.MEDICAL
            else TechnicalService(self.session)
        )

    async def registry_pdf(
        self, principal: Principal, kind: JournalKind, req: ExportRequest
    ) -> tuple[bytes, str]:
        """Формирует PDF-выгрузку по организации и периоду (или по выбранным записям)."""
        settings = get_settings()
        svc = self._service(kind)
        svc._require(principal, svc.perms.export)
        organization_id = (
            principal.org_id if principal.role in CLIENT_ROLES else req.organization_id
        )
        if organization_id is None:
            raise ValidationFailedError("Укажите организацию (organization_id)")
        stmt: Any = await svc._scope(select(svc.model), principal)
        stmt = svc._apply_common_filters(
            stmt,
            RecordFilters(
                organization_id=organization_id, date_from=req.date_from, date_to=req.date_to
            ),
        )
        if req.record_ids:
            stmt = stmt.where(svc.model.id.in_(req.record_ids))
        stmt = stmt.order_by(svc.model.performed_at.asc(), svc.model.id.asc()).limit(
            settings.export_max_rows + 1
        )
        records = list((await self.session.execute(stmt)).scalars().all())
        if not records:
            raise NotFoundError("Нет записей для выгрузки")
        if len(records) > settings.export_max_rows:
            raise ValidationFailedError(
                f"Слишком много записей (максимум {settings.export_max_rows}), сузьте период"
            )
        org = await self.session.get(Organization, organization_id)
        if org is None:
            raise NotFoundError("Организация не найдена")
        docs = await svc.signatures([r.id for r in records])
        date_from = req.date_from or local_date(records[0].performed_at)
        date_to = req.date_to or local_date(records[-1].performed_at)
        period_from = fmt_date_value(date_from)
        period_to = fmt_date_value(date_to)
        pdf = await render_registry_pdf(
            kind=kind,
            customer={
                "name": org.short_name or org.name,
                "inn": org.inn,
                "address": org.legal_address,
            },
            records=records,
            docs=docs,
            period_from=period_from,
            period_to=period_to,
        )
        name = "Отчёт о медосмотрах" if kind is JournalKind.MEDICAL else "Отчёт о техконтроле"
        filename = f"{name} ПРЕДРЕЙС_с {period_from} по {period_to}.pdf"
        await append_audit(
            self.session,
            principal,
            action="report.export",
            entity_type=kind.value,
            entity_id=str(organization_id),
            payload={"rows": len(records), "from": period_from, "to": period_to},
        )
        await self.session.commit()
        return pdf, filename


def fmt_date_value(value: date) -> str:
    """Дата в формате ДД.ММ.ГГГГ."""
    return value.strftime("%d.%m.%Y")


__all__ = ["ExportRequest", "ReportService", "content_disposition", "fmt_date"]

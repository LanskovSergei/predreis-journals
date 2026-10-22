"""Формирование отчётных PDF (Выгрузка) и PDF отдельных записей."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.security import Principal
from app.core.timeutils import local_date
from app.domain.enums import JournalKind
from app.domain.masking import MEDICAL_PRIVACY_NOTICE
from app.domain.permissions import CLIENT_ROLES
from app.models.catalog import Organization
from app.models.documents import RecordDocument
from app.models.records import MedicalRecord, TechnicalRecord
from app.modules.audit.service import append_audit
from app.modules.medical.service import MedicalService
from app.modules.records.base import BaseRecordService
from app.modules.records.schemas import RecordFilters
from app.modules.reports.render import html_to_pdf, render_html
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


def _executor(settings: Settings) -> dict[str, str]:
    """Реквизиты исполнителя из настроек."""
    return {
        "name": settings.executor_name,
        "inn": settings.executor_inn,
        "address": settings.executor_address,
        "phone": settings.executor_phone,
        "email": settings.executor_email,
    }


async def render_single_record_pdf(
    kind: JournalKind, record: MedicalRecord | TechnicalRecord, doc: RecordDocument | None
) -> bytes:
    """PDF одной записи (человекочитаемая часть электронного документа типа 1)."""
    settings = get_settings()
    org = record.snapshot.get("organization", {})
    customer = {
        "name": org.get("short_name") or org.get("name", ""),
        "inn": org.get("inn", ""),
        "address": org.get("legal_address"),
    }
    common: dict[str, Any] = {
        "customer": customer,
        "executor": _executor(settings),
        "period_from": None,
        "period_to": None,
        "stamp": None,
    }
    if kind is JournalKind.MEDICAL:
        assert isinstance(record, MedicalRecord)
        html = render_html(
            "medical_report.html",
            title=MEDICAL_RECORD_TITLE,
            rows=[medical_row(1, record, doc)],
            executor_license=settings.executor_license,
            privacy_notice=MEDICAL_PRIVACY_NOTICE,
            **common,
        )
    else:
        assert isinstance(record, TechnicalRecord)
        html = render_html(
            "technical_report.html",
            title=TECHNICAL_RECORD_TITLE,
            rows=[technical_row(1, record, doc)],
            executor_license=None,
            privacy_notice=None,
            **common,
        )
    return await html_to_pdf(html)


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
        common: dict[str, Any] = {
            "customer": {
                "name": org.short_name or org.name,
                "inn": org.inn,
                "address": org.legal_address,
            },
            "executor": _executor(settings),
            "period_from": fmt_date_value(date_from),
            "period_to": fmt_date_value(date_to),
            "stamp": None,
        }
        if kind is JournalKind.MEDICAL:
            rows = [medical_row(i, r, docs.get(r.id)) for i, r in enumerate(records, 1)]
            html = render_html(
                "medical_report.html",
                title=MEDICAL_TITLE,
                rows=rows,
                executor_license=settings.executor_license,
                privacy_notice=MEDICAL_PRIVACY_NOTICE,
                **common,
            )
            name = "Отчёт о медосмотрах"
        else:
            rows = [technical_row(i, r, docs.get(r.id)) for i, r in enumerate(records, 1)]
            html = render_html(
                "technical_report.html",
                title=TECHNICAL_TITLE,
                rows=rows,
                executor_license=None,
                privacy_notice=None,
                **common,
            )
            name = "Отчёт о техконтроле"
        pdf = await html_to_pdf(html)
        filename = f"{name} ПРЕДРЕЙС_с {common['period_from']} по {common['period_to']}.pdf"
        await append_audit(
            self.session,
            principal,
            action="report.export",
            entity_type=kind.value,
            entity_id=str(organization_id),
            payload={
                "rows": len(records),
                "from": common["period_from"],
                "to": common["period_to"],
            },
        )
        await self.session.commit()
        return pdf, filename


def fmt_date_value(value: date) -> str:
    """Дата в формате ДД.ММ.ГГГГ."""
    return value.strftime("%d.%m.%Y")


__all__ = ["ExportRequest", "ReportService", "content_disposition", "fmt_date"]

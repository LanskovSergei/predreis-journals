"""HTTP-эндпоинты отчётных выгрузок (PDF)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Principal, get_principal
from app.domain.enums import JournalKind
from app.modules.reports.service import ExportRequest, ReportService, content_disposition

router = APIRouter(prefix="/exports", tags=["Выгрузки (PDF)"])


async def _export(
    kind: JournalKind, body: ExportRequest, principal: Principal, session: AsyncSession
) -> Response:
    """Формирует PDF и отдаёт его как вложение."""
    pdf, filename = await ReportService(session).registry_pdf(principal, kind, body)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.post("/medical", summary="Выгрузка журнала медосмотров в PDF")
async def export_medical(
    body: ExportRequest,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """PDF с отфильтрованными записями медосмотров (медданные скрыты)."""
    return await _export(JournalKind.MEDICAL, body, principal, session)


@router.post("/technical", summary="Выгрузка журнала техконтроля в PDF")
async def export_technical(
    body: ExportRequest,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """PDF с отфильтрованными записями техконтроля."""
    return await _export(JournalKind.TECHNICAL, body, principal, session)

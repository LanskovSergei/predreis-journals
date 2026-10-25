"""HTTP-эндпоинты электронных журналов."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NotFoundError
from app.core.security import Principal, get_principal
from app.core.storage import get_storage
from app.domain.enums import EJournalStatus, JournalKind
from app.integrations.predreis.client import get_predreis_client
from app.modules.ejournal.schemas import EJournalCreate, EJournalOut, RejectIn
from app.modules.ejournal.service import EJournalService

router = APIRouter(prefix="/ejournals", tags=["Электронные журналы"])


def _service(session: AsyncSession) -> EJournalService:
    """Создаёт сервис электронных журналов."""
    return EJournalService(session, get_predreis_client())


@router.get("", response_model=list[EJournalOut], summary="Список электронных журналов")
async def list_journals(
    status_filter: EJournalStatus | None = None,
    kind: JournalKind | None = None,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[EJournalOut]:
    """Журналы по статусу и виду (СА — «ожидающие подписи»)."""
    rows = await _service(session).list_journals(principal, status_filter, kind)
    return [EJournalOut.model_validate(r) for r in rows]


@router.post(
    "", response_model=EJournalOut, status_code=status.HTTP_201_CREATED, summary="Сформировать"
)
async def create_journal(
    body: EJournalCreate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> EJournalOut:
    """Создаёт черновик журнала по организации и периоду."""
    return EJournalOut.model_validate(await _service(session).create(principal, body))


@router.get("/{journal_id}", response_model=EJournalOut, summary="Электронный журнал")
async def get_journal(
    journal_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> EJournalOut:
    """Возвращает журнал."""
    return EJournalOut.model_validate(await _service(session).get(principal, journal_id))


@router.delete("/{journal_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Отмена черновика")
async def cancel_journal(
    journal_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Удаляет черновик."""
    await _service(session).cancel(principal, journal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{journal_id}/submit", response_model=EJournalOut, summary="Отправить на подпись")
async def submit_journal(
    journal_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> EJournalOut:
    """Резервирует записи и отправляет журнал в ЛК СА."""
    return EJournalOut.model_validate(await _service(session).submit(principal, journal_id))


@router.post(
    "/{journal_id}/sign",
    response_model=EJournalOut,
    summary="Подписать (СА): постановка в очередь подписи",
)
async def sign_journal(
    journal_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> EJournalOut:
    """Ставит журнал в очередь подписи организации; статус «signing», затем «signed»."""
    return EJournalOut.model_validate(await _service(session).sign(principal, journal_id))


@router.post("/{journal_id}/reject", response_model=EJournalOut, summary="Отклонить (СА)")
async def reject_journal(
    journal_id: uuid.UUID,
    body: RejectIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> EJournalOut:
    """Отклоняет журнал, контейнер расформировывается."""
    return EJournalOut.model_validate(
        await _service(session).reject(principal, journal_id, body.reason)
    )


@router.get("/{journal_id}/preview", summary="Человекочитаемая версия журнала (PDF)")
async def preview_journal(
    journal_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """PDF содержимого журнала для СА: до подписи — без плашки, после — подписанная версия."""
    journal = await _service(session).get(principal, journal_id)
    key = journal.pdf_key if journal.status is EJournalStatus.SIGNED else journal.preview_pdf_key
    if not key:
        raise NotFoundError("Журнал ещё не отправлен на подпись")
    return Response(
        content=await get_storage().get(key),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="journal-{journal.id}.pdf"'},
    )


@router.get("/{journal_id}/download", summary="Скачать ZIP-контейнер")
async def download_journal(
    journal_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Отдаёт собранный ZIP (только после подписи; доступ — Предрейс, Админ, СА)."""
    journal = await _service(session).get(principal, journal_id)
    if journal.status is not EJournalStatus.SIGNED or not journal.zip_key:
        raise NotFoundError("ZIP-контейнер появляется после подписи журнала")
    data = await get_storage().get(journal.zip_key)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="journal-{journal.id}.zip"'},
    )

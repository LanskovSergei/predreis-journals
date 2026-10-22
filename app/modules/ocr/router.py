"""HTTP-эндпоинты распознавания сканов."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.core.security import Principal, require
from app.domain.enums import OcrStampType
from app.domain.permissions import Permission
from app.modules.ocr.service import OcrService

router = APIRouter(prefix="/ocr", tags=["Распознавание сканов"])


@router.post("/batches", status_code=status.HTTP_202_ACCEPTED, summary="Загрузить сканы")
async def create_batch(
    stamp_type: Annotated[OcrStampType, Form()],
    files: Annotated[list[UploadFile], File()],
    principal: Principal = Depends(require(Permission.OCR_UPLOAD)),
) -> dict[str, str]:
    """Загружает сканы путевых листов и запускает распознавание."""
    batch = await OcrService().create_batch(principal, stamp_type, files)
    return {"batch_id": str(batch.id)}


@router.post("/batches/{batch_id}/commit", summary="Преобразовать черновики в записи архива")
async def commit_batch(
    batch_id: uuid.UUID,
    principal: Principal = Depends(require(Permission.OCR_UPLOAD)),
) -> dict[str, int]:
    """Создаёт записи архива из проверенных черновиков."""
    return {"created": await OcrService().commit_batch(principal, batch_id)}

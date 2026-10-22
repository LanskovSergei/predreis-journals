"""Распознавание сканов бумажных путевых листов. ЗАГЛУШКА с описанием шагов (ТЗ, стр. 14-15)."""

from __future__ import annotations

import uuid

from fastapi import UploadFile

from app.core.errors import NotImplementedYetError
from app.core.security import Principal
from app.domain.enums import OcrStampType
from app.models.ocr import OcrBatch


class OcrService:
    """Сервис распознавания: загрузка → OCR → черновики → преобразование в записи архива."""

    async def create_batch(
        self, principal: Principal, stamp_type: OcrStampType, files: list[UploadFile]
    ) -> OcrBatch:
        """Принимает PDF/JPEG/PNG, сохраняет в хранилище, ставит задачу распознавания.

        TODO: валидировать типы и размер; сохранить файлы; создать OcrBatch;
        в воркере вызвать YandexVisionClient.recognize и разобрать штамп выбранного типа
        (предрейсовый / послерейсовый / техконтроль): постоянные поля сопоставить со
        справочниками (организация, ТС, ФИО водителя, ФИО медика/механика), переменные —
        дата, время, одометр. Для каждой строки — OcrItem с parsed и issues
        (зелёный / «новый водитель» / «не удалось распознать» / «сверьте одометр»).
        """
        raise NotImplementedYetError("Распознавание сканов ещё не реализовано")

    async def commit_batch(self, principal: Principal, batch_id: uuid.UUID) -> int:
        """Преобразует проверенные черновики в записи архива (source=ocr), возвращает их число.

        TODO: для каждого OcrItem создать запись через MedicalService/TechnicalService.create
        с source=RecordSource.OCR; строки с непройденной верификацией — в «Примечание».
        """
        raise NotImplementedYetError("Преобразование черновиков в записи ещё не реализовано")

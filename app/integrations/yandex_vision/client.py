"""Клиент Yandex Vision OCR (формат запроса сверить с документацией Yandex Cloud)."""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import UpstreamError

logger = logging.getLogger(__name__)

MIME_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "application/pdf": "PDF"}


class YandexVisionClient:
    """Асинхронный клиент распознавания текста."""

    def __init__(self, settings: Settings) -> None:
        """Сохраняет ключ API, каталог и адрес сервиса."""
        self._url = settings.yandex_vision_url
        self._headers = {
            "Authorization": f"Api-Key {settings.yandex_vision_api_key}",
            "x-folder-id": settings.yandex_vision_folder_id,
            "x-data-logging-enabled": "false",
        }

    async def recognize(self, content: bytes, mime_type: str) -> dict[str, Any]:
        """Распознаёт текст на изображении или PDF и возвращает ответ сервиса как есть."""
        if mime_type not in MIME_TYPES:
            raise UpstreamError(f"Неподдерживаемый тип файла: {mime_type}")
        body = {
            "mimeType": MIME_TYPES[mime_type],
            "languageCodes": ["ru"],
            "model": "page",
            "content": base64.b64encode(content).decode("ascii"),
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(self._url, json=body, headers=self._headers)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Yandex Vision недоступен или вернул ошибку: %s", exc)
            raise UpstreamError("Ошибка распознавания (Yandex Vision)") from exc
        return dict(resp.json())

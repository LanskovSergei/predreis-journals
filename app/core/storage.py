"""Хранилище файлов (XML, PDF, подписи, ZIP). Сейчас — локальная файловая система."""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class Storage(Protocol):
    """Интерфейс хранилища: позволяет заменить диск на S3/MinIO."""

    async def put(self, key: str, data: bytes) -> str:
        """Сохраняет данные и возвращает ключ."""

    async def get(self, key: str) -> bytes:
        """Возвращает содержимое по ключу."""

    async def delete(self, key: str) -> None:
        """Удаляет объект (отсутствие объекта не считается ошибкой)."""


class LocalStorage:
    """Локальное файловое хранилище с защитой от выхода за корневой каталог."""

    def __init__(self, root: Path) -> None:
        """Запоминает корневой каталог хранилища."""
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        """Преобразует ключ в безопасный путь внутри корня."""
        path = (self._root / key).resolve()
        if self._root not in path.parents:
            raise ValueError(f"Недопустимый ключ хранилища: {key!r}")
        return path

    async def put(self, key: str, data: bytes) -> str:
        """Сохраняет данные на диск."""
        path = self._path(key)

        def _write() -> None:
            """Синхронная запись файла."""
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(_write)
        return key

    async def get(self, key: str) -> bytes:
        """Читает данные с диска."""
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        """Удаляет файл, если он существует."""
        path = self._path(key)
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            logger.debug("Файл уже удалён: %s", key)


@lru_cache
def get_storage() -> LocalStorage:
    """Возвращает экземпляр хранилища."""
    return LocalStorage(get_settings().storage_dir)

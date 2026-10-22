"""Прикладные исключения и единый формат ошибок API."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Базовое прикладное исключение с HTTP-статусом и машинным кодом."""

    status_code: int = 400
    code: str = "app_error"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None) -> None:
        """Сохраняет сообщение, необязательный код и детали ошибки."""
        super().__init__(message)
        self.message = message
        self.details = details
        if code is not None:
            self.code = code


class UnauthorizedError(AppError):
    """Нет или некорректен токен."""

    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    """Недостаточно прав."""

    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    """Объект не найден (или недоступен пользователю)."""

    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    """Нарушение бизнес-правила (статус записи, дубликат и т.п.)."""

    status_code = 409
    code = "conflict"


class ValidationFailedError(AppError):
    """Данные формально корректны, но нарушают бизнес-валидацию."""

    status_code = 422
    code = "validation_failed"


class NotImplementedYetError(AppError):
    """Функциональность предусмотрена ТЗ, но ещё не реализована."""

    status_code = 501
    code = "not_implemented"


class UpstreamError(AppError):
    """Ошибка внешней системы (Предрейс, Yandex Vision)."""

    status_code = 502
    code = "upstream_error"


def _payload(code: str, message: str, details: Any = None) -> dict[str, Any]:
    """Собирает тело ответа об ошибке."""
    return {"error": {"code": code, "message": message, "details": details}}


def register_exception_handlers(app: FastAPI) -> None:
    """Подключает обработчики ошибок с единым JSON-форматом."""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        """Обрабатывает прикладные ошибки."""
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.code, exc.message, jsonable_encoder(exc.details)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        """Обрабатывает ошибки валидации запроса."""
        return JSONResponse(
            status_code=422,
            content=_payload(
                "request_invalid", "Некорректный запрос", jsonable_encoder(exc.errors())
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        """Логирует непредвиденные ошибки и отдаёт безопасный ответ."""
        logger.exception("Необработанная ошибка: %s", exc)
        return JSONResponse(
            status_code=500, content=_payload("internal_error", "Внутренняя ошибка сервера")
        )

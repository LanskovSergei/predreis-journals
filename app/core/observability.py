"""Наблюдаемость: идентификатор запроса, журнал обращений, заголовки безопасности, метрики HTTP.

В журнал обращений пишутся метод, шаблон маршрута, статус и время, но **не строка запроса и не
тело**: в параметрах поиска бывают фамилии водителей (персональные данные).
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from contextvars import ContextVar

from prometheus_client import Histogram
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
access_log = logging.getLogger("journals.access")

_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_QUIET = ("/health", "/ready", "/metrics")

HTTP_SECONDS = Histogram(
    "journals_http_request_seconds",
    "Время обработки HTTP-запроса",
    ["method", "route", "status"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)


class RequestIdFilter(logging.Filter):
    """Добавляет в каждую запись журнала идентификатор текущего запроса."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Дописывает `request_id`; запись не отбрасывается."""
        record.request_id = request_id_var.get()
        return True


def route_template(scope: Scope) -> str:
    """Шаблон маршрута с префиксом и именами параметров (`/api/v1/medical/records/{record_id}`).

    Реальные значения параметров в метки и журнал не попадают: иначе число меток росло бы без
    предела, а значения (идентификаторы, перечисления) выбирал бы клиент.
    Если маршрут не найден, возвращается `unmatched`.
    """
    route = scope.get("route")
    path = getattr(route, "path", None)
    if not path:
        return "unmatched"
    template = [s for s in path.split("/") if s]
    real = [s for s in scope["path"].split("/") if s]
    if len(template) > len(real):
        return str(path)
    return "/" + "/".join(real[: len(real) - len(template)] + template)


def clean_request_id(raw: str | None) -> str:
    """Принимает входящий идентификатор только если он безопасен, иначе создаёт новый."""
    if raw and _VALID_ID.match(raw):
        return raw
    return uuid.uuid4().hex


class ObservabilityMiddleware:
    """ASGI-прослойка: идентификатор запроса, заголовки безопасности, метрики, журнал обращений."""

    def __init__(self, app: ASGIApp) -> None:
        """Оборачивает приложение."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Обрабатывает HTTP-запрос; остальные типы пропускает без изменений."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id")
        rid = clean_request_id(incoming.decode("latin-1") if incoming else None)
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status = 500
        is_api = scope["path"].startswith("/api/")

        async def send_wrapper(message: Message) -> None:
            """Дописывает заголовки в ответ."""
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = rid
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                if is_api:
                    headers["Cache-Control"] = "no-store"  # ответы содержат персональные данные
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - started
            route = route_template(scope)
            if scope["path"] not in _QUIET:
                HTTP_SECONDS.labels(scope["method"], route, str(status)).observe(elapsed)
                access_log.info(
                    "%s %s -> %s %.0f мс [%s]", scope["method"], route, status, elapsed * 1000, rid
                )
            request_id_var.reset(token)

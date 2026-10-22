"""Проверка HMAC-подписи входящих событий Предрейса."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping

from app.core.config import Settings
from app.core.errors import UnauthorizedError


def sign_body(secret: str, timestamp: str, body: bytes) -> str:
    """Считает HMAC-SHA256 от «timestamp.body» (используется и в тестах/на стороне Предрейса)."""
    msg = timestamp.encode("ascii") + b"." + body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_request(
    body: bytes, headers: Mapping[str, str], settings: Settings, *, now: float | None = None
) -> None:
    """Проверяет заголовки X-Timestamp и X-Signature; защищает от подделки и повторов."""
    if not settings.predreis_hmac_secret:
        raise UnauthorizedError("Интеграция не настроена", code="integration_disabled")
    timestamp = headers.get("x-timestamp", "")
    signature = headers.get("x-signature", "")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise UnauthorizedError("Некорректный X-Timestamp") from exc
    current = time.time() if now is None else now
    if abs(current - ts) > settings.hmac_tolerance_s:
        raise UnauthorizedError("Просроченный запрос", code="stale_request")
    expected = sign_body(settings.predreis_hmac_secret, timestamp, body)
    if not hmac.compare_digest(expected, signature):
        raise UnauthorizedError("Неверная подпись запроса", code="bad_signature")

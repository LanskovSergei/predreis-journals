"""Ограничение частоты попыток (скользящее окно, в памяти процесса)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    """Разрешает не более `limit` событий на ключ за `window_s` секунд."""

    def __init__(
        self, limit: int, window_s: float, now: Callable[[], float] = time.monotonic
    ) -> None:
        """Запоминает лимит, окно и источник времени (подменяется в тестах)."""
        self._limit, self._window, self._now = limit, window_s, now
        self._events: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Учитывает попытку; False, если лимит окна уже исчерпан."""
        now = self._now()
        events = self._events.setdefault(key, deque())
        while events and events[0] <= now - self._window:
            events.popleft()
        if len(events) >= self._limit:
            return False
        events.append(now)
        return True

    def blocked(self, key: str) -> bool:
        """True, если лимит окна уже исчерпан (сама проверка попыток не считает)."""
        now = self._now()
        events = self._events.get(key)
        if not events:
            return False
        while events and events[0] <= now - self._window:
            events.popleft()
        return len(events) >= self._limit

    def record(self, key: str) -> None:
        """Записывает одно событие (например, неудачную попытку входа)."""
        self._events.setdefault(key, deque()).append(self._now())

    def reset(self, key: str) -> None:
        """Сбрасывает счётчик ключа (после успешного входа)."""
        self._events.pop(key, None)


class LoginGuard:
    """Защита входа от подбора пароля: считаются только неудачные попытки.

    По почте порог низкий (подбор пароля одной учётной записи), по адресу выше: за одним адресом
    (офис, NAT) работает много людей, и успешные входы блокировать нельзя.
    """

    def __init__(
        self,
        per_email: int,
        per_ip: int,
        window_s: float,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        """Задаёт пороги неудач для почты и адреса и окно в секундах."""
        self._email = SlidingWindowLimiter(per_email, window_s, now)
        self._ip = SlidingWindowLimiter(per_ip, window_s, now)

    def is_blocked(self, ip: str, email: str) -> bool:
        """Нужно ли отказать во входе, не обращаясь в Предрейс."""
        return self._ip.blocked(f"ip:{ip}") or self._email.blocked(f"email:{email}")

    def failure(self, ip: str, email: str) -> None:
        """Учитывает неудачную попытку (неверный пароль)."""
        self._ip.record(f"ip:{ip}")
        self._email.record(f"email:{email}")

    def success(self, email: str) -> None:
        """Успешный вход снимает счётчик по почте (по адресу неудачи стареют сами)."""
        self._email.reset(f"email:{email}")

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

    def reset(self, key: str) -> None:
        """Сбрасывает счётчик ключа (после успешного входа)."""
        self._events.pop(key, None)

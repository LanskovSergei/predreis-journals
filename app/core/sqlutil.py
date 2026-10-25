"""Мелкие вспомогательные функции для SQL-запросов."""

from __future__ import annotations


def contains_pattern(value: str) -> str:
    """Готовит шаблон LIKE «содержит» с экранированием спецсимволов."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"

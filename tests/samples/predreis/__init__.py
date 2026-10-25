"""Образцы сообщений и ответов Предрейса (сняты с рабочей системы 25.10.2026, ПДн заменены заглушками)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent


def load(name: str) -> Any:
    """Загружает образец по имени файла (копия, можно менять)."""
    return copy.deepcopy(json.loads((_DIR / name).read_text(encoding="utf-8")))

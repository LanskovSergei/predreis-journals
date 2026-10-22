"""Защита сведений, составляющих врачебную тайну (ст. 13 323-ФЗ)."""

from __future__ import annotations

from typing import Any

NOT_AVAILABLE = "N/A"

MEDICAL_SECRET_FIELDS: frozenset[str] = frozenset(
    {
        "complaints",
        "blood_pressure",
        "pulse",
        "temperature",
        "alcohol_mgl",
        "harmful_factors",
    }
)

MEDICAL_PRIVACY_NOTICE = (
    "Информация, имеющая отношение к врачебной тайне, скрыта в соответствии со ст. 13 "
    "Федерального закона от 21.11.2011 № 323-ФЗ «Об основах охраны здоровья граждан "
    "в Российской Федерации»."
)


def redact_medical(row: dict[str, Any]) -> dict[str, Any]:
    """Возвращает копию строки, где скрытые поля заменены на N/A (для PDF)."""
    return {k: (NOT_AVAILABLE if k in MEDICAL_SECRET_FIELDS else v) for k, v in row.items()}

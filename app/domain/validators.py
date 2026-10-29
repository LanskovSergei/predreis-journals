"""Предметные проверки: СНИЛС, одометр, спорные данные записи."""

from __future__ import annotations

import re
from datetime import date

MIN_DRIVER_AGE = 18
MAX_DRIVER_AGE = 75  # эвристика для метки «спорные данные»; значение согласовать


def validate_snils(value: str) -> bool:
    """Проверяет СНИЛС: 11 цифр и корректное контрольное число."""
    digits = re.sub(r"\D", "", value)
    if len(digits) != 11:
        return False
    total = sum(int(d) * w for d, w in zip(digits[:9], range(9, 0, -1), strict=True))
    if total < 100:
        control = total
    elif total in (100, 101):
        control = 0
    else:
        control = total % 101
        if control == 100:
            control = 0
    return control == int(digits[9:])


def odometer_issues(previous: int | None, current: int, following: int | None) -> list[str]:
    """Проверяет нарастающую последовательность показаний одометра (ТЗ, стр. 14)."""
    issues: list[str] = []
    if previous is not None and current < previous:
        issues.append(f"Одометр меньше предыдущего выезда ({previous})")
    if following is not None and current > following:
        issues.append(f"Одометр больше следующего выезда ({following})")
    return issues


def birth_date_issue(birth_date: date, on_date: date) -> str | None:
    """Возвращает описание проблемы с датой рождения водителя или None."""
    if birth_date >= on_date:
        return "Дата рождения водителя позже даты осмотра"
    age = (
        on_date.year
        - birth_date.year
        - ((on_date.month, on_date.day) < (birth_date.month, birth_date.day))
    )
    if age < MIN_DRIVER_AGE or age > MAX_DRIVER_AGE:
        return f"Сверьте дату рождения водителя (возраст {age})"
    return None


def merge_auto_note(note: str | None, issues: list[str]) -> str | None:
    """Добавляет метки о спорных данных в «Примечание», не дублируя уже имеющиеся."""
    base = (note or "").strip()
    additions = [i for i in issues if i not in base]
    if not additions:
        return base or None
    return "; ".join([p for p in [base, *additions] if p])


# Латинские буквы, похожие на кириллические на госномере (номер вводят с любой раскладки).
_PLATE_LATIN = str.maketrans("ABEKMHOPCTYX", "АВЕКМНОРСТУХ")


def normalize_plate(value: str) -> str:
    """Госномер для сравнения: без пробелов и дефисов, верхний регистр, латиница → кириллица."""
    return "".join(value.split()).replace("-", "").upper().translate(_PLATE_LATIN)


def validate_inn(value: str) -> bool:
    """Проверяет ИНН организации (10 цифр) или ИП (12 цифр) по контрольным разрядам."""
    if not value.isdigit() or len(value) not in (10, 12):
        return False
    d = [int(c) for c in value]

    def check(weights: list[int]) -> int:
        return sum(w * x for w, x in zip(weights, d, strict=False)) % 11 % 10

    if len(d) == 10:
        return check([2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[9]
    return (
        check([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[10]
        and check([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[11]
    )

"""Тесты предметных валидаторов."""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.validators import (
    birth_date_issue,
    merge_auto_note,
    odometer_issues,
    validate_snils,
)


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("112-233-445 95", True),
        ("11223344595", True),
        ("112-233-445 96", False),
        ("123", False),
        ("", False),
    ],
)
def test_validate_snils(value: str, ok: bool) -> None:
    """СНИЛС проверяется по длине и контрольному числу."""
    assert validate_snils(value) is ok


def test_odometer_must_be_non_decreasing() -> None:
    """Показания одометра не могут быть меньше предыдущего и больше следующего выезда."""
    assert odometer_issues(1000, 1100, 1200) == []
    assert odometer_issues(1000, 900, None)
    assert odometer_issues(None, 1300, 1200)
    assert odometer_issues(None, 10, None) == []


def test_birth_date_issue() -> None:
    """Подозрительные даты рождения помечаются."""
    on = date(2026, 10, 14)
    assert birth_date_issue(date(1980, 1, 1), on) is None
    assert birth_date_issue(date(2026, 10, 15), on)
    assert birth_date_issue(date(2015, 1, 1), on)
    assert birth_date_issue(date(1930, 1, 1), on)


def test_merge_auto_note_is_idempotent() -> None:
    """Метки не дублируются при повторном применении."""
    note = merge_auto_note("Проверить", ["Одометр меньше"])
    assert note == "Проверить; Одометр меньше"
    assert merge_auto_note(note, ["Одометр меньше"]) == note
    assert merge_auto_note(None, []) is None

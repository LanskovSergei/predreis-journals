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


def test_inn_checksum() -> None:
    """ИНН организации (10 цифр) и ИП (12 цифр) проверяются по контрольным разрядам."""
    from app.domain.validators import validate_inn

    assert validate_inn("7707083893")  # реальный ИНН (ПАО Сбербанк)
    assert not validate_inn("7707083894")  # испорчен контрольный разряд
    assert validate_inn("500100732259")  # пример ИНН ИП из открытых источников
    assert not validate_inn("500100732250")
    for bad in ("", "77070838", "77070838931", "abcdefghij"):
        assert not validate_inn(bad)


def test_plate_normalization_handles_layout_and_spaces() -> None:
    """Госномер сравнивается без пробелов и регистра, латиница заменяется похожей кириллицей."""
    from app.domain.validators import normalize_plate

    assert normalize_plate(" о 224 ек 790 ") == "О224ЕК790"
    assert normalize_plate("O224EK790") == "О224ЕК790"  # латиница
    assert normalize_plate("а123-вс77") == "А123ВС77"

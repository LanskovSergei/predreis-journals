"""Сертификаты Предрейса: разбор ответа, серийные номера, статусы (формат ответа предположительный)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.integrations.predreis.certificates import (
    best_certificate,
    normalize_serial,
    parse_certificate,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
UID = uuid.UUID("32b933cf-f31a-4e55-b0be-39a221a64ed7")


def valid_item(**over: object) -> dict[str, object]:
    """Элемент ответа с действующим сертификатом (имена полей кроме serial/issuer/is_valid — предположение)."""
    return {
        "user_id": str(UID),
        "full_name": "Сидорова Анна Сергеевна",
        "role": "medic",
        "owner": "Сидорова Анна Сергеевна",
        "thumbprint": "A1B2C3D4E5F60718293A4B5C6D7E8F9012345678",
        "serial": "0x0F18DD73747ECCC4AB0D2B1EE00D4040",
        "issuer": "ООО «Удостоверяющий центр»",
        "valid_from": "2025-09-17T00:00:00+00:00",
        "valid_to": "2027-06-19T00:00:00+00:00",
        "is_valid": True,
    } | over


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0x0F18DD73747ECCC4AB0D2B1EE00D4040", "0f18dd73747eccc4ab0d2b1ee00d4040"),
        ("0F18DD73747ECCC4AB0D2B1EE00D4040", "0f18dd73747eccc4ab0d2b1ee00d4040"),
        ("0x f1:8d d7", "f18dd7"),
        ("0xABC", "0abc"),  # нечётная длина дополняется до целых байтов
        ("", None),
        (None, None),
        ("0xZZ", None),
    ],
)
def test_serial_is_normalized_like_the_one_in_the_signature(
    raw: str | None, expected: str | None
) -> None:
    """Номер из Предрейса (`0x…`) приводится к виду, который мы достаём из CMS-подписи."""
    assert normalize_serial(raw) == expected


def test_valid_certificate_is_parsed_and_active() -> None:
    """Действующий сертификат: все поля разобраны, статус active."""
    cert = parse_certificate(valid_item())
    assert cert is not None and cert.user_id == UID
    assert cert.serial == "0f18dd73747eccc4ab0d2b1ee00d4040"
    assert cert.issuer == "ООО «Удостоверяющий центр»" and cert.owner == "Сидорова Анна Сергеевна"
    assert cert.status(NOW) == "active" and not cert.expiring_soon(NOW)


def test_missing_certificate_has_no_data_and_is_not_called_expired() -> None:
    """22 из 29 записей: сертификата в хранилище нет, поля пустые, is_valid=false → missing, не expired."""
    cert = parse_certificate(
        valid_item(
            serial=None, issuer=None, valid_from=None, valid_to=None, owner=None, is_valid=False
        )
    )
    assert cert is not None
    assert cert.serial is None and cert.valid_to is None
    assert cert.status(NOW) == "missing" and not cert.expiring_soon(NOW)


def test_expired_and_invalid_flag() -> None:
    """Срок прошёл или Предрейс отметил недействительным → expired."""
    past = parse_certificate(valid_item(valid_to="2026-01-01T00:00:00+00:00"))
    flagged = parse_certificate(valid_item(is_valid=False))
    assert past is not None and past.status(NOW) == "expired"
    assert flagged is not None and flagged.status(NOW) == "expired"


def test_expiring_soon_within_thirty_days() -> None:
    """Предупреждение «скоро истекает»: действующий сертификат, до конца срока 30 дней и меньше."""
    soon = parse_certificate(valid_item(valid_to=(NOW + timedelta(days=12)).isoformat()))
    later = parse_certificate(valid_item(valid_to=(NOW + timedelta(days=90)).isoformat()))
    assert soon is not None and soon.expiring_soon(NOW)
    assert later is not None and not later.expiring_soon(NOW)


def test_alternative_field_names_and_date_only_values() -> None:
    """Формат ответа не сверен с образцом: принимаются синонимы имён, даты без времени считаются UTC."""
    item = {
        "user": {"id": str(UID), "full_name": "Иванов", "role": "mechanic"},
        "certificate": {"owner": "Иванов И.И.", "thumbprint": "ab", "serial_number": "0xAB12"},
        "not_before": "2025-01-01",
        "not_after": "2027-01-01",
        "issuer": "УЦ",
        "valid": True,
    }
    cert = parse_certificate(item)
    assert cert is not None and cert.role == "mechanic" and cert.full_name == "Иванов"
    assert cert.serial == "ab12" and cert.valid_to == datetime(
        2027, 1, 1, 23, 59, 59, tzinfo=timezone.utc
    )
    assert cert.status(NOW) == "active"


def test_item_without_user_id_is_skipped() -> None:
    """Элемент без идентификатора пользователя пропускается, а не роняет весь список."""
    assert parse_certificate({"serial": "0x01", "is_valid": True}) is None
    assert parse_certificate({"user_id": "не-uuid"}) is None


def test_best_certificate_prefers_active_with_latest_expiry() -> None:
    """У специалиста несколько сертификатов (ТЗ: «сертификат 1, сертификат 2»): берётся лучший."""
    old = parse_certificate(valid_item(valid_to="2026-01-01T00:00:00+00:00"))
    a = parse_certificate(valid_item(valid_to="2027-03-01T00:00:00+00:00", serial="0x01"))
    b = parse_certificate(valid_item(valid_to="2028-03-01T00:00:00+00:00", serial="0x02"))
    missing = parse_certificate(valid_item(valid_to=None, is_valid=False))
    assert old and a and b and missing
    assert best_certificate([old, missing, a, b], NOW) is b
    assert (
        best_certificate([old, missing], NOW) is old
    )  # просроченный всё же полезнее, чем «нет данных»
    assert best_certificate([], NOW) is None


def test_real_sample_from_predreis() -> None:
    """Настоящий образец ответа Предрейса: ФИО частями, владелец в cert_cn, даты «ДД.ММ.ГГГГ»."""
    import json
    from pathlib import Path

    item = json.loads(
        (Path(__file__).parent / "samples" / "predreis" / "certificate.json").read_text("utf-8")
    )
    cert = parse_certificate(item)
    assert cert is not None
    assert cert.full_name == "Иванова Анна Сергеевна" and cert.owner == "Иванова Анна"
    assert cert.serial == "01449ad1f8dfb225a640085edd019fff3a"  # 0x… → вид из подписи
    assert cert.thumbprint == "7dbfee891d6600e68a4a2c2554b9604359540e3a"
    assert cert.issuer and "Тензор" in cert.issuer
    assert cert.valid_from == datetime(2026, 8, 14, tzinfo=timezone.utc)
    assert cert.valid_to == datetime(
        2027, 8, 14, 23, 59, 59, tzinfo=timezone.utc
    )  # весь последний день
    assert cert.status(NOW) == "active"
    last_day = datetime(2027, 8, 14, 18, 0, tzinfo=timezone.utc)
    assert (
        cert.status(last_day) == "active"
        and cert.status(last_day + timedelta(days=1)) == "expired"
    )

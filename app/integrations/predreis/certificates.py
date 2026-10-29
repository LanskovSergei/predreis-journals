"""Сертификаты пользователей из метода Предрейса `GET /api/v1/service/certificates`.

Формат сверен с образцом Предрейса (tests/samples/predreis/certificate.json): ФИО частями
(`last_name`, `first_name`, `middle_name`), владелец по сертификату `cert_cn`, `thumbprint`,
серийный номер `0x…` (как в КриптоПро), `issuer`, сроки вида «14.08.2027», `is_valid`. Синонимы
имён полей тоже принимаются. Отзыв Предрейс не проверяет.

У 22 из 29 записей сертификата в хранилище КриптоПро нет: `serial`, `issuer` и сроки пустые,
`is_valid=false`. Они получают статус `missing` («нет действующего сертификата»), а не «истёк»:
по этим данным нельзя отличить истёкший сертификат от удалённого.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from app.integrations.predreis.events import pick

CertStatus = Literal["active", "expired", "missing"]
EXPIRING_SOON = timedelta(days=30)


def normalize_serial(value: Any) -> str | None:
    """Серийный номер единым видом: без `0x`, строчными, целыми байтами (как в CMS-подписи).

    Нужен, чтобы сопоставлять номер из Предрейса (`0x0F18…`) с номером из самой подписи.
    """
    if value in (None, ""):
        return None
    text = str(value).strip().lower().replace(" ", "").replace(":", "")
    text = text.removeprefix("0x")
    if not text or any(c not in "0123456789abcdef" for c in text):
        return None
    return text if len(text) % 2 == 0 else "0" + text


def _dt(value: Any, *, end_of_day: bool = False) -> datetime | None:
    """Дата из ответа: «14.08.2027» (формат Предрейса) или ISO 8601; без времени считается UTC.

    Для даты окончания без времени берётся конец суток: сертификат действует весь последний день.
    """
    if not value:
        return None
    text = str(value).strip()
    date_only = False
    try:
        if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", text):
            parsed = datetime.strptime(text, "%d.%m.%Y")
            date_only = True
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            date_only = re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) is not None
    except ValueError:
        return None
    if date_only and end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class UserCertificate:
    """Сертификат пользователя Предрейса."""

    user_id: uuid.UUID
    full_name: str
    role: str
    owner: str | None
    thumbprint: str | None
    serial: str | None
    issuer: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    is_valid: bool

    def status(self, now: datetime | None = None) -> CertStatus:
        """active, expired или missing (данных о сертификате нет)."""
        now = now or datetime.now(timezone.utc)
        if self.valid_to is None:
            return "missing"
        if self.valid_from is not None and now < self.valid_from:
            return "missing"
        return "active" if (self.is_valid and now <= self.valid_to) else "expired"

    def expiring_soon(self, now: datetime | None = None) -> bool:
        """Действующий сертификат истекает в ближайшие 30 дней."""
        now = now or datetime.now(timezone.utc)
        return (
            self.status(now) == "active"
            and self.valid_to is not None
            and self.valid_to - now <= EXPIRING_SOON
        )


def _cert_field(item: dict[str, Any], *names: str) -> Any:
    """Поле сертификата: имя ищется на верхнем уровне и внутри блоков `certificate` и `cert`."""
    paths = [n for name in names for n in (name, f"certificate.{name}", f"cert.{name}")]
    return pick(item, *paths)


def _full_name(item: dict[str, Any]) -> str:
    """ФИО: целиком, если пришло одним полем, иначе из фамилии, имени и отчества."""
    whole = pick(item, "full_name", "user_name", "user.full_name", "name")
    if whole:
        return str(whole)
    parts = (pick(item, k, f"user.{k}") for k in ("last_name", "first_name", "middle_name"))
    return " ".join(str(x) for x in parts if x)


def parse_certificate(item: dict[str, Any]) -> UserCertificate | None:
    """Разбирает элемент ответа; элемент без идентификатора пользователя пропускается (None)."""
    raw_id = pick(item, "user_id", "user.id", "id")
    try:
        user_id = uuid.UUID(str(raw_id))
    except ValueError:
        return None
    valid = _cert_field(item, "is_valid", "valid")
    return UserCertificate(
        user_id=user_id,
        full_name=_full_name(item),
        role=str(pick(item, "role", "user.role", "user_role") or ""),
        owner=_cert_field(item, "cert_cn", "owner", "cert_owner", "subject"),
        thumbprint=_cert_field(item, "thumbprint", "fingerprint"),
        serial=normalize_serial(_cert_field(item, "serial", "serial_number")),
        issuer=_cert_field(item, "issuer", "ca", "authority"),
        valid_from=_dt(_cert_field(item, "valid_from", "not_before", "start_date")),
        valid_to=_dt(
            _cert_field(item, "valid_to", "not_after", "expires_at", "end_date"), end_of_day=True
        ),
        is_valid=bool(valid) if valid is not None else False,
    )


def best_certificate(
    certs: list[UserCertificate], now: datetime | None = None
) -> UserCertificate | None:
    """Лучший сертификат: действующий с самым поздним сроком, иначе самый свежий по сроку."""
    if not certs:
        return None
    order = {"active": 0, "expired": 1, "missing": 2}
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return min(certs, key=lambda c: (order[c.status(now)], -(c.valid_to or epoch).timestamp()))

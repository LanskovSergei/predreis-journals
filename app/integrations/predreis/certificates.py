"""Сертификаты пользователей из метода Предрейса `GET /api/v1/service/certificates`.

Предрейс описал ответ словами: пользователь (ФИО, роль), владелец по сертификату, отпечаток,
серийный номер вида `0x…` (как в КриптоПро), удостоверяющий центр, сроки, признак `is_valid`.
Имена `serial`, `issuer`, `is_valid` названы прямо, остальные поля принимаются в нескольких
вариантах написания: формат нужно сверить по образцу ответа. Отзыв Предрейс не проверяет.

У 22 из 29 записей сертификата в хранилище КриптоПро нет: `serial`, `issuer` и сроки пустые,
`is_valid=false`. Они получают статус `missing` («нет действующего сертификата»), а не «истёк»:
по этим данным нельзя отличить истёкший сертификат от удалённого.
"""

from __future__ import annotations

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


def _dt(value: Any) -> datetime | None:
    """Дата или дата-время из ответа; без часового пояса считается UTC."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
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
        full_name=str(pick(item, "full_name", "user_name", "user.full_name", "name") or ""),
        role=str(pick(item, "role", "user.role", "user_role") or ""),
        owner=_cert_field(item, "owner", "cert_owner", "subject"),
        thumbprint=_cert_field(item, "thumbprint", "fingerprint"),
        serial=normalize_serial(_cert_field(item, "serial", "serial_number")),
        issuer=_cert_field(item, "issuer", "ca", "authority"),
        valid_from=_dt(_cert_field(item, "valid_from", "not_before", "start_date")),
        valid_to=_dt(_cert_field(item, "valid_to", "not_after", "expires_at", "end_date")),
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

"""Сертификаты и счётчики специалистов (плашки стартовых страниц, ТЗ стр. 9-17)."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Protocol

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ForbiddenError, UpstreamError
from app.core.security import Principal
from app.domain.enums import RecordStatus, Role
from app.domain.permissions import Permission, has_permission
from app.integrations.predreis.certificates import (
    UserCertificate,
    best_certificate,
    parse_certificate,
)
from app.models.catalog import User
from app.models.records import MedicalRecord, TechnicalRecord
from app.modules.specialists.schemas import (
    CertificateOut,
    MyCertificatesOut,
    RecordCounters,
    SpecialistOut,
    SpecialistsOut,
)

logger = logging.getLogger(__name__)
SPECIALIST_ROLES: dict[Role, Any] = {Role.MEDIC: MedicalRecord, Role.MECHANIC: TechnicalRecord}


class CertificateSource(Protocol):
    """Источник сертификатов (клиент Предрейса или заглушка в тестах)."""

    async def list_certificates(
        self, *, role: str | None = None, user_id: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        """Сырой список сертификатов."""


_cache: dict[tuple[str | None, uuid.UUID | None], tuple[float, list[UserCertificate]]] = {}


def clear_cache() -> None:
    """Сбрасывает кэш (для тестов и принудительного обновления)."""
    _cache.clear()


async def fetch_certificates(
    source: CertificateSource, *, role: str | None = None, user_id: uuid.UUID | None = None
) -> list[UserCertificate]:
    """Сертификаты из Предрейса с кэшем на `certificates_cache_ttl_s` секунд."""
    key = (role, user_id)
    hit = _cache.get(key)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]
    parsed = [
        c for item in await source.list_certificates(role=role, user_id=user_id)
        if (c := parse_certificate(item)) is not None
    ]  # fmt: skip
    _cache[key] = (time.monotonic() + get_settings().certificates_cache_ttl_s, parsed)
    return parsed


def to_out(cert: UserCertificate) -> CertificateOut:
    """Сертификат в виде для API."""
    return CertificateOut(
        serial=cert.serial,
        owner=cert.owner,
        thumbprint=cert.thumbprint,
        issuer=cert.issuer,
        valid_from=cert.valid_from,
        valid_to=cert.valid_to,
        status=cert.status(),
        expiring_soon=cert.expiring_soon(),
    )


class SpecialistsService:
    """Сертификаты специалистов и счётчики их записей."""

    def __init__(self, session: AsyncSession, source: CertificateSource) -> None:
        """Принимает сессию БД и источник сертификатов."""
        self.session = session
        self.source = source

    async def my_certificates(self, principal: Principal) -> MyCertificatesOut:
        """Сертификаты самого медика или механика (стартовая страница)."""
        if principal.role not in SPECIALIST_ROLES:
            raise ForbiddenError("Доступно только медику и механику", code="permission_denied")
        certs = await fetch_certificates(self.source, user_id=principal.user_id)
        best = best_certificate(certs)
        return MyCertificatesOut(
            status=best.status() if best else "missing",
            valid_to=best.valid_to if best else None,
            certificates=[to_out(c) for c in certs],
        )

    async def list_specialists(self, principal: Principal, role: Role) -> SpecialistsOut:
        """Медики или механики с сертификатами; счётчики записей только для СА (ТЗ, стр. 17)."""
        if not has_permission(principal.role, Permission.CATALOG_VIEW):
            raise ForbiddenError("Недостаточно прав", code="permission_denied")
        if role not in SPECIALIST_ROLES:
            raise ForbiddenError(
                "Список доступен для медиков и механиков", code="permission_denied"
            )
        available = True
        try:
            certs = await fetch_certificates(self.source, role=role.value)
        except UpstreamError as exc:
            logger.warning("Сертификаты недоступны, показываем специалистов без них: %s", exc)
            certs, available = [], False
        by_user: dict[uuid.UUID, list[UserCertificate]] = {}
        names: dict[uuid.UUID, str] = {}
        for cert in certs:
            by_user.setdefault(cert.user_id, []).append(cert)
            names[cert.user_id] = cert.full_name or names.get(cert.user_id, "")
        # специалисты, известные журналам, даже без записи о сертификате в Предрейсе
        known = (await self.session.execute(select(User).where(User.role == role))).scalars().all()
        for user in known:
            names.setdefault(user.id, user.full_name)
            names[user.id] = names[user.id] or user.full_name
        counters = await self._counters(role) if principal.role is Role.SA else {}
        items: list[SpecialistOut] = []
        for user_id, name in names.items():
            user_certs = by_user.get(user_id, [])
            best = best_certificate(user_certs)
            items.append(
                SpecialistOut(
                    user_id=user_id,
                    full_name=name,
                    role=role.value,  # type: ignore[arg-type]
                    status=best.status() if best else "missing",
                    valid_to=best.valid_to if best else None,
                    expiring_soon=best.expiring_soon() if best else False,
                    certificates=[to_out(c) for c in user_certs],
                    records=counters.get(user_id, RecordCounters(to_sign=0, signed=0, total=0))
                    if principal.role is Role.SA
                    else None,
                )
            )
        items.sort(key=lambda i: i.full_name.lower())
        return SpecialistsOut(items=items, certificates_available=available)

    async def _counters(self, role: Role) -> dict[uuid.UUID, RecordCounters]:
        """Счётчики записей по специалистам одним запросом."""
        model = SPECIALIST_ROLES[role]
        unsigned = case((model.status == RecordStatus.UNSIGNED, 1), else_=0)
        rows = await self.session.execute(
            select(model.specialist_user_id, func.sum(unsigned), func.count()).group_by(
                model.specialist_user_id
            )
        )
        result: dict[uuid.UUID, RecordCounters] = {}
        for user_id, to_sign, total in rows.all():
            waiting = int(to_sign or 0)
            result[user_id] = RecordCounters(
                to_sign=waiting, signed=int(total) - waiting, total=int(total)
            )
        return result

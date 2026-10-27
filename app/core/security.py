"""Аутентификация: токен пользователя выдаёт Предрейс, журналы только проверяют его у Предрейса.

Секрет подписи токенов остаётся в Предрейсе. Ответ проверки кэшируется на короткое время, поэтому
отключение доступа вступает в силу за секунды, а нагрузка на Предрейс невелика.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ForbiddenError, UnauthorizedError
from app.domain.enums import Role
from app.domain.permissions import Permission, has_permission
from app.integrations.predreis.client import PredreisClient, VerifiedUser, get_predreis_client

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)

# Названия ролей в Предрейсе, отличающиеся от наших. Оператор платформы пишется «predreise».
_ROLE_ALIASES = {
    "super_admin": Role.SA,
    "super-admin": Role.SA,
    "predreise": Role.PREDREIS,
}


@dataclass(frozen=True, slots=True)
class Principal:
    """Аутентифицированный пользователь. Сам токен в объекте не хранится."""

    user_id: uuid.UUID
    role: Role
    journals_access: bool
    org_id: uuid.UUID | None
    full_name: str
    ip: str | None = None
    session_id: str | None = None


def parse_role(value: str) -> Role:
    """Роль Предрейса → роль журналов; неизвестная роль не получает доступа."""
    normalized = value.strip().lower()
    if normalized in _ROLE_ALIASES:
        return _ROLE_ALIASES[normalized]
    try:
        return Role(normalized)
    except ValueError as exc:
        logger.warning("Неизвестная роль пользователя из Предрейса: %r", value)
        raise ForbiddenError("Роль не поддерживается журналами", code="role_unsupported") from exc


def principal_from_user(
    user: VerifiedUser, *, ip: str | None = None, token: str = ""
) -> Principal:
    """Строит Principal из ответа Предрейса; идентификатор сессии — короткий хеш токена."""
    if not user.is_active:
        raise UnauthorizedError("Учётная запись отключена")
    if not user.journals_access:
        raise ForbiddenError("Доступ к журналам не предоставлен", code="journals_disabled")
    return Principal(
        user_id=user.id,
        role=parse_role(user.role),
        journals_access=True,
        org_id=user.org_id,
        full_name=user.full_name,
        ip=ip,
        session_id=hashlib.sha256(token.encode()).hexdigest()[:16] if token else None,
    )


class UserVerifier:
    """Проверка токенов пользователей через Предрейс с кэшем успехов и коротким кэшем отказов."""

    def __init__(
        self,
        client: PredreisClient,
        settings: Settings,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        """Принимает клиент Предрейса, настройки и источник времени (подменяется в тестах)."""
        self._client = client
        self._settings = settings
        self._now = now
        # ключ — SHA-256 токена (сам токен в памяти не держим): (истекает, пользователь | отказ)
        self._cache: dict[str, tuple[float, VerifiedUser | AppError]] = {}

    def invalidate(self, token: str) -> None:
        """Забывает результат проверки токена (например, при выходе)."""
        self._cache.pop(hashlib.sha256(token.encode()).hexdigest(), None)

    def _store(self, key: str, ttl: int, value: VerifiedUser | AppError) -> None:
        """Кладёт результат в кэш, вытесняя самые старые записи при переполнении."""
        if len(self._cache) >= self._settings.auth_cache_max:
            for old in list(self._cache)[: max(1, len(self._cache) // 10)]:
                del self._cache[old]
        self._cache[key] = (self._now() + ttl, value)

    async def verify(self, token: str) -> VerifiedUser:
        """Возвращает пользователя либо бросает ошибку доступа (401/403)."""
        key = hashlib.sha256(token.encode()).hexdigest()
        hit = self._cache.get(key)
        if hit is not None and hit[0] > self._now():
            if isinstance(hit[1], AppError):
                raise type(hit[1])(hit[1].message, code=hit[1].code)
            return hit[1]
        try:
            user = await self._client.verify_user(token)
        except (UnauthorizedError, ForbiddenError) as exc:
            self._store(key, self._settings.auth_negative_cache_ttl_s, exc)
            raise
        self._store(key, self._settings.auth_cache_ttl_s, user)
        return user


@lru_cache
def get_user_verifier() -> UserVerifier:
    """Общий экземпляр проверки токенов."""
    return UserVerifier(get_predreis_client(), get_settings())


async def get_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    verifier: UserVerifier = Depends(get_user_verifier),
) -> Principal:
    """Зависимость FastAPI: текущий пользователь с доступом к журналам."""
    if creds is None:
        raise UnauthorizedError("Требуется авторизация")
    user = await verifier.verify(creds.credentials)
    ip = request.client.host if request.client else None
    return principal_from_user(user, ip=ip, token=creds.credentials)


def require(permission: Permission) -> Callable[[Principal], Awaitable[Principal]]:
    """Фабрика зависимости: требует наличие права у роли пользователя."""

    async def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        """Проверяет право и возвращает пользователя."""
        if not has_permission(principal.role, permission):
            raise ForbiddenError("Недостаточно прав", code="permission_denied")
        return principal

    return _dep

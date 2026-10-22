"""Аутентификация: проверка JWT Предрейса (RS256, ключи из JWKS) и права доступа."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.errors import ForbiddenError, UnauthorizedError, UpstreamError
from app.domain.enums import Role
from app.domain.permissions import Permission, has_permission

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class Principal:
    """Аутентифицированный пользователь (данные из JWT Предрейса)."""

    user_id: uuid.UUID
    role: Role
    journals_access: bool
    org_id: uuid.UUID | None
    full_name: str
    raw_token: str
    ip: str | None = None
    session_id: str | None = None


class JwksCache:
    """Кэш публичных ключей Предрейса с периодическим обновлением."""

    def __init__(self, url: str, ttl_s: int) -> None:
        """Запоминает адрес JWKS и время жизни кэша."""
        self._url = url
        self._ttl = ttl_s
        self._keys: dict[str, Any] = {}
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()

    async def _refresh(self) -> None:
        """Скачивает набор ключей и обновляет кэш."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self._url)
                resp.raise_for_status()
                jwks = jwt.PyJWKSet.from_dict(resp.json())
        except (httpx.HTTPError, ValueError, jwt.PyJWKSetError) as exc:
            raise UpstreamError("Не удалось получить ключи Предрейса (JWKS)") from exc
        self._keys = {k.key_id: k for k in jwks.keys if k.key_id}
        self._loaded_at = time.monotonic()

    async def get_key(self, kid: str) -> Any:
        """Возвращает ключ по kid; при промахе один раз обновляет кэш."""
        async with self._lock:
            expired = time.monotonic() - self._loaded_at > self._ttl
            if expired or kid not in self._keys:
                await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise UnauthorizedError("Неизвестный ключ подписи токена")
        return key.key


@lru_cache
def get_jwks_cache() -> JwksCache:
    """Возвращает общий кэш JWKS."""
    settings = get_settings()
    return JwksCache(settings.jwks_url, settings.jwks_cache_ttl_s)


async def decode_token(token: str, settings: Settings, jwks: JwksCache) -> dict[str, Any]:
    """Проверяет подпись и claims токена, возвращает payload."""
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        if not kid:
            raise UnauthorizedError("В заголовке токена нет kid")
        key = await jwks.get_key(kid)
        payload: dict[str, Any] = jwt.decode(
            token,
            key=key,
            algorithms=settings.jwt_algorithms,
            audience=settings.jwt_audience,
            issuer=settings.predreis_issuer,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Недействительный токен") from exc
    return payload


def principal_from_claims(claims: dict[str, Any], token: str, ip: str | None = None) -> Principal:
    """Строит Principal из claims: sub, role, journals_access, org_id, name, sid."""
    try:
        org = claims.get("org_id")
        return Principal(
            user_id=uuid.UUID(str(claims["sub"])),
            role=Role(claims["role"]),
            journals_access=bool(claims.get("journals_access", False)),
            org_id=uuid.UUID(str(org)) if org else None,
            full_name=str(claims.get("name", "")),
            raw_token=token,
            ip=ip,
            session_id=claims.get("sid"),
        )
    except (KeyError, ValueError) as exc:
        raise UnauthorizedError("Некорректные claims токена") from exc


async def get_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    """Зависимость FastAPI: текущий пользователь с доступом к журналам."""
    if creds is None:
        raise UnauthorizedError("Требуется авторизация")
    claims = await decode_token(creds.credentials, get_settings(), get_jwks_cache())
    ip = request.client.host if request.client else None
    principal = principal_from_claims(claims, creds.credentials, ip)
    if not principal.journals_access:
        raise ForbiddenError("Доступ к электронным журналам не включён", code="journals_disabled")
    return principal


def require(permission: Permission) -> Callable[[Principal], Awaitable[Principal]]:
    """Фабрика зависимости: требует наличие права у роли пользователя."""

    async def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        """Проверяет право и возвращает пользователя."""
        if not has_permission(principal.role, permission):
            raise ForbiddenError("Недостаточно прав", code="permission_denied")
        return principal

    return _dep

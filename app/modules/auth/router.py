"""Вход пользователей: те же почта и пароль, что в Предрейсе."""

from __future__ import annotations

import logging
import uuid
from functools import lru_cache

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, SecretStr

from app.core.config import get_settings
from app.core.errors import TooManyRequestsError, UnauthorizedError
from app.core.ratelimit import LoginGuard
from app.core.security import (
    UserVerifier,
    get_user_verifier,
    principal_from_user,
)
from app.domain.enums import Role
from app.domain.permissions import PERMISSION_ROLES, has_permission
from app.integrations.predreis.client import PredreisClient, get_predreis_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Вход"])


class LoginIn(BaseModel):
    """Почта и пароль пользователя Предрейса."""

    email: str = Field(min_length=3, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=1000)


class UserOut(BaseModel):
    """Пользователь в ответе входа."""

    id: uuid.UUID
    full_name: str
    role: Role
    organization_id: uuid.UUID | None


class LoginOut(BaseModel):
    """Токен (выдан Предрейсом), профиль и права для построения интерфейса."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int | None = None
    user: UserOut
    permissions: list[str]


@lru_cache
def get_login_limiter() -> LoginGuard:
    """Защита входа от подбора: неудачи по почте и по адресу."""
    settings = get_settings()
    return LoginGuard(
        settings.login_max_attempts, settings.login_max_attempts_per_ip, settings.login_window_s
    )


@router.post(
    "/login", response_model=LoginOut, summary="Вход теми же почтой и паролем, что в Предрейсе"
)
async def login(
    body: LoginIn,
    request: Request,
    client: PredreisClient = Depends(get_predreis_client),
    verifier: UserVerifier = Depends(get_user_verifier),
    limiter: LoginGuard = Depends(get_login_limiter),
) -> LoginOut:
    """Проверяет учётные данные в Предрейсе и открыт ли доступ к журналам; возвращает токен.

    Пароль передаётся только в Предрейс и не сохраняется. Считаются только неудачные попытки.
    """
    ip = request.client.host if request.client else "?"
    email = body.email.strip().lower()
    if limiter.is_blocked(ip, email):
        raise TooManyRequestsError("Слишком много неудачных попыток входа, повторите позже")
    try:
        login_result = await client.user_login(email, body.password.get_secret_value())
    except UnauthorizedError:
        limiter.failure(ip, email)
        raise
    user = await verifier.verify(login_result.access_token)
    principal = principal_from_user(user, ip=ip, token=login_result.access_token)
    limiter.success(email)
    logger.info("Вход пользователя %s (%s)", principal.user_id, principal.role.value)
    return LoginOut(
        access_token=login_result.access_token,
        expires_in=login_result.expires_in,
        user=UserOut(
            id=principal.user_id,
            full_name=principal.full_name,
            role=principal.role,
            organization_id=principal.org_id,
        ),
        permissions=sorted(p.value for p in PERMISSION_ROLES if has_permission(principal.role, p)),
    )

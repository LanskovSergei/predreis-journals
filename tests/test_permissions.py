"""Сверка матрицы прав с таблицей «Ролевые права» из ТЗ (стр. 8)."""

from __future__ import annotations

import pytest

from app.domain.enums import Role
from app.domain.permissions import PERMISSION_ROLES, Permission, has_permission

C, D, M, T, P, A, S = (
    Role.CLIENT,
    Role.DISPATCHER,
    Role.MEDIC,
    Role.MECHANIC,
    Role.PREDREIS,
    Role.ADMIN,
    Role.SA,
)

TZ_TABLE: dict[Permission, set[Role]] = {
    Permission.MEDICAL_VIEW: {M, P, A, S},
    Permission.MEDICAL_CREATE: {M, P, A, S},
    Permission.MEDICAL_EDIT: {M, P, A, S},
    Permission.MEDICAL_DELETE_UNSIGNED: {M, P, A, S},
    Permission.MEDICAL_REQUEST_DELETE: {P},
    Permission.MEDICAL_DELETE_SIGNED: {A, S},
    Permission.MEDICAL_SIGN: {M},
    Permission.MEDICAL_EXPORT: {C, D, M, P, A, S},
    Permission.MEDICAL_EJOURNAL_BUILD: {P, A, S},
    Permission.MEDICAL_EJOURNAL_SIGN: {S},
    Permission.TECHNICAL_VIEW: {T, P, A, S},
    Permission.TECHNICAL_CREATE: {T, P, A, S},
    Permission.TECHNICAL_DELETE_UNSIGNED: {T, P, A, S},
    Permission.TECHNICAL_REQUEST_DELETE: {P},
    Permission.TECHNICAL_DELETE_SIGNED: {A, S},
    Permission.TECHNICAL_SIGN: {T},
    Permission.TECHNICAL_EXPORT: {C, D, T, P, A, S},
    Permission.TECHNICAL_EJOURNAL_BUILD: {P, A, S},
    Permission.TECHNICAL_EJOURNAL_SIGN: {S},
}


@pytest.mark.parametrize("permission", list(TZ_TABLE))
def test_matches_tz_table(permission: Permission) -> None:
    """Роли каждого права совпадают с таблицей ТЗ."""
    assert set(PERMISSION_ROLES[permission]) == TZ_TABLE[permission]


def test_every_permission_has_roles() -> None:
    """Для каждого права задан непустой набор ролей."""
    for perm in Permission:
        assert PERMISSION_ROLES[perm], perm


def test_only_specialists_sign_records() -> None:
    """Подписывать записи личным сертификатом могут только медик и механик."""
    assert has_permission(M, Permission.MEDICAL_SIGN)
    assert not has_permission(S, Permission.MEDICAL_SIGN)
    assert not has_permission(M, Permission.TECHNICAL_SIGN)

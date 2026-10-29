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


def test_every_permission_has_a_title() -> None:
    """У каждого права есть название для документа."""
    from app.domain.permissions import PERMISSION_TITLES

    assert set(PERMISSION_TITLES) == set(Permission)


def test_permissions_doc_is_up_to_date() -> None:
    """docs/PERMISSIONS.md совпадает с матрицей в коде (если упал: python scripts/gen_permissions_doc.py)."""
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "gen_permissions_doc", root / "scripts" / "gen_permissions_doc.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    committed = (root / "docs" / "PERMISSIONS.md").read_text(encoding="utf-8")
    assert committed == module.render(), (
        "docs/PERMISSIONS.md устарел: python scripts/gen_permissions_doc.py"
    )

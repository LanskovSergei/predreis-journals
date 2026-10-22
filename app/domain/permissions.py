"""Матрица прав доступа (ТЗ, стр. 8, «Ролевые права»). Единый источник истины."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.enums import JournalKind, Role

STAFF_ROLES = frozenset({Role.MEDIC, Role.MECHANIC, Role.PREDREIS, Role.ADMIN, Role.SA})
CLIENT_ROLES = frozenset({Role.CLIENT, Role.DISPATCHER})
MANAGER_ROLES = frozenset({Role.PREDREIS, Role.ADMIN, Role.SA})


class Permission(str, Enum):
    """Атомарные права."""

    # Журнал медицинских осмотров
    MEDICAL_VIEW = "medical:view"
    MEDICAL_VIEW_OWN_ORG = "medical:view_own_org"
    MEDICAL_CREATE = "medical:create"
    MEDICAL_EDIT = "medical:edit"
    MEDICAL_DELETE_UNSIGNED = "medical:delete_unsigned"
    MEDICAL_REQUEST_DELETE = "medical:request_delete"
    MEDICAL_DELETE_SIGNED = "medical:delete_signed"
    MEDICAL_SIGN = "medical:sign"
    MEDICAL_EXPORT = "medical:export"
    MEDICAL_EJOURNAL_BUILD = "medical:ejournal_build"
    MEDICAL_EJOURNAL_SIGN = "medical:ejournal_sign"
    # Журнал технического контроля
    TECHNICAL_VIEW = "technical:view"
    TECHNICAL_VIEW_OWN_ORG = "technical:view_own_org"
    TECHNICAL_CREATE = "technical:create"
    TECHNICAL_EDIT = "technical:edit"
    TECHNICAL_DELETE_UNSIGNED = "technical:delete_unsigned"
    TECHNICAL_REQUEST_DELETE = "technical:request_delete"
    TECHNICAL_DELETE_SIGNED = "technical:delete_signed"
    TECHNICAL_SIGN = "technical:sign"
    TECHNICAL_EXPORT = "technical:export"
    TECHNICAL_EJOURNAL_BUILD = "technical:ejournal_build"
    TECHNICAL_EJOURNAL_SIGN = "technical:ejournal_sign"
    # Общие разделы
    CATALOG_VIEW = "catalog:view"
    CATALOG_MANAGE = "catalog:manage"
    OCR_UPLOAD = "ocr:upload"
    STATS_VIEW = "stats:view"
    EJOURNAL_VIEW = "ejournal:view"


_M, _T = Role.MEDIC, Role.MECHANIC
_P, _A, _S = Role.PREDREIS, Role.ADMIN, Role.SA
_C, _D = Role.CLIENT, Role.DISPATCHER

PERMISSION_ROLES: dict[Permission, frozenset[Role]] = {
    Permission.MEDICAL_VIEW: frozenset({_M, _P, _A, _S}),
    Permission.MEDICAL_VIEW_OWN_ORG: frozenset({_C, _D}),
    Permission.MEDICAL_CREATE: frozenset({_M, _P, _A, _S}),
    Permission.MEDICAL_EDIT: frozenset({_M, _P, _A, _S}),
    Permission.MEDICAL_DELETE_UNSIGNED: frozenset({_M, _P, _A, _S}),
    Permission.MEDICAL_REQUEST_DELETE: frozenset({_P}),
    Permission.MEDICAL_DELETE_SIGNED: frozenset({_A, _S}),
    Permission.MEDICAL_SIGN: frozenset({_M}),
    Permission.MEDICAL_EXPORT: frozenset({_C, _D, _M, _P, _A, _S}),
    Permission.MEDICAL_EJOURNAL_BUILD: frozenset({_P, _A, _S}),
    Permission.MEDICAL_EJOURNAL_SIGN: frozenset({_S}),
    Permission.TECHNICAL_VIEW: frozenset({_T, _P, _A, _S}),
    Permission.TECHNICAL_VIEW_OWN_ORG: frozenset({_C, _D}),
    Permission.TECHNICAL_CREATE: frozenset({_T, _P, _A, _S}),
    # В ТЗ права на редактирование техконтроля не указаны — по аналогии с медосмотрами.
    Permission.TECHNICAL_EDIT: frozenset({_T, _P, _A, _S}),
    Permission.TECHNICAL_DELETE_UNSIGNED: frozenset({_T, _P, _A, _S}),
    Permission.TECHNICAL_REQUEST_DELETE: frozenset({_P}),
    Permission.TECHNICAL_DELETE_SIGNED: frozenset({_A, _S}),
    Permission.TECHNICAL_SIGN: frozenset({_T}),
    Permission.TECHNICAL_EXPORT: frozenset({_C, _D, _T, _P, _A, _S}),
    Permission.TECHNICAL_EJOURNAL_BUILD: frozenset({_P, _A, _S}),
    Permission.TECHNICAL_EJOURNAL_SIGN: frozenset({_S}),
    Permission.CATALOG_VIEW: frozenset({_P, _A, _S}),
    Permission.CATALOG_MANAGE: frozenset({_P, _A, _S}),
    Permission.OCR_UPLOAD: frozenset({_P, _A, _S}),
    Permission.STATS_VIEW: frozenset({_M, _T, _P, _A, _S}),
    Permission.EJOURNAL_VIEW: frozenset({_P, _A, _S}),
}


def has_permission(role: Role, permission: Permission) -> bool:
    """Проверяет, есть ли у роли указанное право."""
    return role in PERMISSION_ROLES[permission]


@dataclass(frozen=True, slots=True)
class RecordPerms:
    """Набор прав для одного вида журнала."""

    view: Permission
    view_own_org: Permission
    create: Permission
    edit: Permission
    delete_unsigned: Permission
    request_delete: Permission
    delete_signed: Permission
    sign: Permission
    export: Permission
    ejournal_build: Permission
    ejournal_sign: Permission


RECORD_PERMS: dict[JournalKind, RecordPerms] = {
    JournalKind.MEDICAL: RecordPerms(
        view=Permission.MEDICAL_VIEW,
        view_own_org=Permission.MEDICAL_VIEW_OWN_ORG,
        create=Permission.MEDICAL_CREATE,
        edit=Permission.MEDICAL_EDIT,
        delete_unsigned=Permission.MEDICAL_DELETE_UNSIGNED,
        request_delete=Permission.MEDICAL_REQUEST_DELETE,
        delete_signed=Permission.MEDICAL_DELETE_SIGNED,
        sign=Permission.MEDICAL_SIGN,
        export=Permission.MEDICAL_EXPORT,
        ejournal_build=Permission.MEDICAL_EJOURNAL_BUILD,
        ejournal_sign=Permission.MEDICAL_EJOURNAL_SIGN,
    ),
    JournalKind.TECHNICAL: RecordPerms(
        view=Permission.TECHNICAL_VIEW,
        view_own_org=Permission.TECHNICAL_VIEW_OWN_ORG,
        create=Permission.TECHNICAL_CREATE,
        edit=Permission.TECHNICAL_EDIT,
        delete_unsigned=Permission.TECHNICAL_DELETE_UNSIGNED,
        request_delete=Permission.TECHNICAL_REQUEST_DELETE,
        delete_signed=Permission.TECHNICAL_DELETE_SIGNED,
        sign=Permission.TECHNICAL_SIGN,
        export=Permission.TECHNICAL_EXPORT,
        ejournal_build=Permission.TECHNICAL_EJOURNAL_BUILD,
        ejournal_sign=Permission.TECHNICAL_EJOURNAL_SIGN,
    ),
}

"""Конечный автомат записи архива: А (unsigned) → Б (signed) → В (in_journal)."""

from __future__ import annotations

import uuid

from app.core.errors import ConflictError, ForbiddenError
from app.domain.enums import RecordSource, RecordStatus

ALLOWED_TRANSITIONS: dict[RecordStatus, frozenset[RecordStatus]] = {
    RecordStatus.UNSIGNED: frozenset({RecordStatus.SIGNED}),
    RecordStatus.SIGNED: frozenset({RecordStatus.IN_JOURNAL}),
    RecordStatus.IN_JOURNAL: frozenset(),
}


def ensure_transition(current: RecordStatus, new: RecordStatus) -> None:
    """Проверяет допустимость перехода между статусами записи."""
    if new not in ALLOWED_TRANSITIONS[current]:
        raise ConflictError(
            f"Переход {current.value} → {new.value} недопустим", code="invalid_transition"
        )


def ensure_editable(status: RecordStatus, source: RecordSource) -> None:
    """Редактировать можно только неподписанную запись не из ЭПЛ."""
    if source is RecordSource.EPL:
        raise ConflictError("Записи из ЭПЛ не редактируются", code="epl_immutable")
    if status is not RecordStatus.UNSIGNED:
        raise ConflictError("Подписанную запись изменять нельзя", code="record_immutable")


def ensure_deletable_unsigned(status: RecordStatus, source: RecordSource) -> None:
    """Прямое удаление допустимо только для неподписанной записи не из ЭПЛ (тип А)."""
    ensure_editable(status, source)


def ensure_signable(
    *,
    status: RecordStatus,
    source: RecordSource,
    note: str | None,
    deletion_pending: bool,
    specialist_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> None:
    """Проверяет условия подписи записи (ТЗ, стр. 7)."""
    if source is RecordSource.EPL:
        raise ConflictError("Записи из ЭПЛ подписывать не нужно", code="epl_immutable")
    if status is not RecordStatus.UNSIGNED:
        raise ConflictError("Запись уже подписана", code="already_signed")
    if note and note.strip():
        raise ConflictError("Запись с примечанием подписать нельзя", code="note_not_empty")
    if deletion_pending:
        raise ConflictError("Запись поставлена на удаление", code="deletion_pending")
    if specialist_id != actor_id:
        raise ForbiddenError(
            "Подписать запись может только специалист, проводивший осмотр",
            code="not_record_specialist",
        )


def ensure_deletion_requestable(
    *,
    status: RecordStatus,
    source: RecordSource,
    deletion_pending: bool,
    reserved_journal_id: uuid.UUID | None,
) -> None:
    """Запрос на удаление — только для подписанной записи (тип Б) вне журнала и не из ЭПЛ."""
    if source is RecordSource.EPL:
        raise ConflictError("Записи из ЭПЛ не удаляются", code="epl_immutable")
    if status is not RecordStatus.SIGNED:
        raise ConflictError(
            "Запрос на удаление возможен только для подписанной записи", code="invalid_status"
        )
    if reserved_journal_id is not None:
        raise ConflictError("Запись включена в электронный журнал", code="in_journal")
    if deletion_pending:
        raise ConflictError("Запись уже поставлена на удаление", code="deletion_pending")


def ensure_signed_deletable(
    *, status: RecordStatus, source: RecordSource, reserved_journal_id: uuid.UUID | None
) -> None:
    """Удаление подписанной записи (СА/Админ): не из ЭПЛ и не включена в журнал."""
    if source is RecordSource.EPL:
        raise ConflictError("Записи из ЭПЛ не удаляются", code="epl_immutable")
    if status is not RecordStatus.SIGNED or reserved_journal_id is not None:
        raise ConflictError(
            "Запись импортирована в электронный журнал и неизменяема", code="in_journal"
        )

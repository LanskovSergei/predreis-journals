"""Тесты конечного автомата записи."""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import ConflictError, ForbiddenError
from app.domain import fsm
from app.domain.enums import RecordSource, RecordStatus

U = uuid.uuid4()


def _signable(**over: object) -> dict[str, object]:
    """Параметры для ensure_signable с допустимыми значениями по умолчанию."""
    base: dict[str, object] = {
        "status": RecordStatus.UNSIGNED,
        "source": RecordSource.MANUAL,
        "note": None,
        "deletion_pending": False,
        "specialist_id": U,
        "actor_id": U,
    }
    return {**base, **over}


def test_transitions_are_linear() -> None:
    """А → Б → В, назад и через шаг нельзя."""
    fsm.ensure_transition(RecordStatus.UNSIGNED, RecordStatus.SIGNED)
    fsm.ensure_transition(RecordStatus.SIGNED, RecordStatus.IN_JOURNAL)
    with pytest.raises(ConflictError):
        fsm.ensure_transition(RecordStatus.UNSIGNED, RecordStatus.IN_JOURNAL)
    with pytest.raises(ConflictError):
        fsm.ensure_transition(RecordStatus.SIGNED, RecordStatus.UNSIGNED)


def test_edit_rules() -> None:
    """Редактируется только неподписанная запись не из ЭПЛ."""
    fsm.ensure_editable(RecordStatus.UNSIGNED, RecordSource.MANUAL)
    for status in (RecordStatus.SIGNED, RecordStatus.IN_JOURNAL):
        with pytest.raises(ConflictError):
            fsm.ensure_editable(status, RecordSource.MANUAL)
    with pytest.raises(ConflictError):
        fsm.ensure_editable(RecordStatus.UNSIGNED, RecordSource.EPL)


def test_sign_rules() -> None:
    """Подпись: нужна чистая запись из бумажного ПЛ и именно тот специалист."""
    fsm.ensure_signable(**_signable())  # type: ignore[arg-type]
    with pytest.raises(ConflictError):
        fsm.ensure_signable(**_signable(note="спорно"))  # type: ignore[arg-type]
    with pytest.raises(ConflictError):
        fsm.ensure_signable(**_signable(source=RecordSource.EPL))  # type: ignore[arg-type]
    with pytest.raises(ConflictError):
        fsm.ensure_signable(**_signable(status=RecordStatus.SIGNED))  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError):
        fsm.ensure_signable(**_signable(actor_id=uuid.uuid4()))  # type: ignore[arg-type]


def test_deletion_request_rules() -> None:
    """Запрос на удаление: только Б, не из ЭПЛ, не в журнале и не повторно."""
    ok = {
        "status": RecordStatus.SIGNED,
        "source": RecordSource.MANUAL,
        "deletion_pending": False,
        "reserved_journal_id": None,
    }
    fsm.ensure_deletion_requestable(**ok)  # type: ignore[arg-type]
    for over in (
        {"status": RecordStatus.UNSIGNED},
        {"source": RecordSource.EPL},
        {"deletion_pending": True},
        {"reserved_journal_id": uuid.uuid4()},
    ):
        with pytest.raises(ConflictError):
            fsm.ensure_deletion_requestable(**{**ok, **over})  # type: ignore[arg-type]

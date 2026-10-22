"""Триггеры БД: неизменяемость подписанных записей и append-only аудит.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUDIT_FN = """
CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only' USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;
"""

# Последняя линия обороны: правила ТЗ (стр. 6-7, 21) дублируются на уровне БД.
#  - unsigned (А): можно менять; допустим переход только в signed;
#  - signed (Б): меняются только status, reserved_journal_id, deletion_pending, updated_at;
#    переход только в in_journal;
#  - in_journal (В): любые изменения запрещены;
#  - удаление: unsigned, либо signed не из ЭПЛ и вне журнала.
RECORD_FN = """
CREATE OR REPLACE FUNCTION record_immutable() RETURNS trigger AS $$
DECLARE
    volatile_cols text[] := ARRAY['status', 'reserved_journal_id', 'deletion_pending', 'updated_at'];
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'unsigned'
           OR (OLD.status = 'signed' AND OLD.source <> 'epl' AND OLD.reserved_journal_id IS NULL) THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'record % cannot be deleted in status %', OLD.id, OLD.status
            USING ERRCODE = 'check_violation';
    END IF;

    IF OLD.status = 'unsigned' THEN
        IF NEW.status NOT IN ('unsigned', 'signed') THEN
            RAISE EXCEPTION 'invalid status transition % -> %', OLD.status, NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'signed' THEN
        IF NEW.status NOT IN ('signed', 'in_journal') THEN
            RAISE EXCEPTION 'invalid status transition % -> %', OLD.status, NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
        IF (to_jsonb(NEW) - volatile_cols) IS DISTINCT FROM (to_jsonb(OLD) - volatile_cols) THEN
            RAISE EXCEPTION 'signed record % is immutable', OLD.id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'record % included in e-journal is immutable', OLD.id
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    """Создаёт функции и триггеры."""
    op.execute(AUDIT_FN)
    op.execute(
        "CREATE TRIGGER trg_audit_log_immutable BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()"
    )
    op.execute(RECORD_FN)
    for table in ("medical_records", "technical_records"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION record_immutable()"
        )


def downgrade() -> None:
    """Удаляет триггеры и функции."""
    for table in ("medical_records", "technical_records"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS record_immutable()")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable()")

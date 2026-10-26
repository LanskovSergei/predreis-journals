"""Индексы для списков и поиска, инвариант «пустого примечания не бывает».

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = {
    "medical_records": ("driver_name", "(snapshot -> 'driver') ->> 'full_name'"),
    "technical_records": ("plate", "(snapshot -> 'vehicle') ->> 'plate'"),
}


def upgrade() -> None:
    """Создаёт индексы и ограничение (триграммы для поиска по подстроке)."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for table, (name, expr) in TABLES.items():
        # Пустое примечание нормализуется в NULL приложением; ограничение закрепляет это в БД.
        op.execute(
            f"UPDATE {table} SET note = NULL WHERE note IS NOT NULL AND length(btrim(note)) = 0"
        )
        op.create_check_constraint(
            "note_not_blank", table, "note IS NULL OR length(btrim(note)) > 0"
        )
        op.execute(f"CREATE INDEX ix_{table}_performed ON {table} (performed_at DESC, id DESC)")
        op.execute(
            f"CREATE INDEX ix_{table}_with_note ON {table} (performed_at DESC) WHERE note IS NOT NULL"
        )
        op.execute(
            f"CREATE INDEX ix_{table}_{name}_trgm ON {table} USING gin (({expr}) gin_trgm_ops)"
        )


def downgrade() -> None:
    """Удаляет индексы и ограничение (расширение pg_trgm остаётся)."""
    for table, (name, _) in TABLES.items():
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_{name}_trgm")
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_with_note")
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_performed")
        op.drop_constraint("ck_" + table + "_note_not_blank", table, type_="check")

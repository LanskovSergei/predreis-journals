"""Поле пробы на алкоголь называется по единице хранения: промилле.

Колонка называлась alcohol_mgl, хотя хранились промилле (так присылает ЭПЛ и так решил заказчик).
В шапке отчётного PDF остаётся mg/L (требование Минздрава), значения там скрыты.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Переименовывает колонку (данные и ограничения сохраняются)."""
    op.alter_column("medical_records", "alcohol_mgl", new_column_name="alcohol_permille")


def downgrade() -> None:
    """Возвращает прежнее имя."""
    op.alter_column("medical_records", "alcohol_permille", new_column_name="alcohol_mgl")

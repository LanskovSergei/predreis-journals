"""Ручной каталог: происхождение карточек и отдельный идентификатор Предрейса.

Организации, водители и ТС могут быть из платформы ПРЕДРЕЙС или добавлены вручную (бумажные клиенты,
водители и машины гибридных клиентов). Идентификатор Предрейса хранится в `predreis_id`, чтобы карточку,
добавленную вручную, можно было объединить с платформой без смены нашего id.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("organizations", "drivers", "vehicles")


def upgrade() -> None:
    """Добавляет колонки; существующие карточки все из платформы, их predreis_id равен id."""
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "origin",
                sa.Enum("platform", "manual", name="catalogorigin", native_enum=False, length=32),
                server_default="platform",
                nullable=False,
            ),
        )
        op.add_column(table, sa.Column("predreis_id", sa.Uuid(), nullable=True))
        op.execute(f"UPDATE {table} SET predreis_id = id")
        op.create_unique_constraint(f"uq_{table}_predreis_id", table, ["predreis_id"])


def downgrade() -> None:
    """Удаляет колонки (карточки, добавленные вручную, при этом останутся без признака)."""
    for table in TABLES:
        op.drop_constraint(f"uq_{table}_predreis_id", table, type_="unique")
        op.drop_column(table, "predreis_id")
        op.drop_column(table, "origin")

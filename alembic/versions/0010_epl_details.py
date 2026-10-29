"""Подробности готовности организации к ЭПЛ из Предрейса.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Колонка с составляющими признака epl_ready и остатком суточного лимита."""
    op.add_column("organizations", sa.Column("epl_details", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    """Удаляет колонку."""
    op.drop_column("organizations", "epl_details")

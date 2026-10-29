"""Подпись КЭП организации: режим подписи в задаче, подписант может отсутствовать.

Электронный журнал подписывается КЭП организации ПРЕДРЕЙС (`sign_as=organization`), пользователь
при этом не передаётся. Записи по-прежнему подписывает специалист (`sign_as=user`).

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет режим подписи; подписант обязателен только для подписи специалистом."""
    op.add_column(
        "sign_jobs", sa.Column("sign_as", sa.String(16), server_default="user", nullable=False)
    )
    op.alter_column("sign_jobs", "signer_user_id", existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint(
        "sign_jobs_signer_required",
        "sign_jobs",
        "sign_as IN ('user', 'organization') AND (sign_as = 'organization' OR signer_user_id IS NOT NULL)",
    )


def downgrade() -> None:
    """Возвращает обязательного подписанта (задачи КЭП организации должны быть завершены)."""
    op.drop_constraint("sign_jobs_signer_required", "sign_jobs", type_="check")
    op.alter_column("sign_jobs", "signer_user_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("sign_jobs", "sign_as")

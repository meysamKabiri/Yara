"""add payment due date

Revision ID: 20260617_0006
Revises: 20260617_0005
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260617_0006"
down_revision: str | None = "20260617_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payment", sa.Column("due_date", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("payment", "due_date")

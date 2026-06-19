"""add worker profile fields

Revision ID: 20260619_0001
Revises: 20260618_0001
Create Date: 2026-06-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_0001"
down_revision: str | None = "20260618_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("worker", sa.Column("daily_rate", sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column("worker", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("worker", "notes")
    op.drop_column("worker", "daily_rate")

"""add project description

Revision ID: 20260628_0001
Revises: 20260627_0002
Create Date: 2026-06-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260628_0001"
down_revision: str | None = "20260627_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("project", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("project", "description")

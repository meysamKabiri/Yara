"""add semantic traceability to history

Revision ID: 20260617_0005
Revises: 20260617_0004
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260617_0005"
down_revision: str | None = "20260617_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("historyentry", sa.Column("rule_id", sa.String(length=100), nullable=True))
    op.add_column("historyentry", sa.Column("explanation", sa.JSON(), nullable=True))
    op.add_column("historyentry", sa.Column("conflict_warnings", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("historyentry", "conflict_warnings")
    op.drop_column("historyentry", "explanation")
    op.drop_column("historyentry", "rule_id")

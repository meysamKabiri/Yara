"""add structured_interpretation to PendingInterpretation

Revision ID: 20260618_0001
Revises: 20260617_0010
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260618_0001"
down_revision: str | None = "20260617_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("pendinginterpretation")}
    if "structured_interpretation" not in columns:
        op.add_column(
            "pendinginterpretation",
            sa.Column("structured_interpretation", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("pendinginterpretation")}
    if "structured_interpretation" in columns:
        op.drop_column("pendinginterpretation", "structured_interpretation")

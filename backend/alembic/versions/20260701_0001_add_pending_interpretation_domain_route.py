"""add domain_route to pending interpretations

Revision ID: 20260701_0001
Revises: 20260630_0003
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260701_0001"
down_revision: str | None = "20260630_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("pendinginterpretation")}
    if "domain_route" not in columns:
        op.add_column(
            "pendinginterpretation",
            sa.Column("domain_route", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("pendinginterpretation")}
    if "domain_route" in columns:
        op.drop_column("pendinginterpretation", "domain_route")

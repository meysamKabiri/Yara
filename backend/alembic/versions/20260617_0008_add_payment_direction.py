"""add payment direction

Revision ID: 20260617_0008
Revises: 20260617_0007
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260617_0008"
down_revision: str | None = "20260617_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("payment")}
    if "direction" not in columns:
        op.add_column(
            "payment",
            sa.Column(
                "direction",
                sa.Enum("INCOMING", "OUTGOING", "DEBT", "DEFERRED", native_enum=False, length=20),
                nullable=False,
                server_default="OUTGOING",
            ),
        )
    op.alter_column("payment", "direction", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("payment")}
    if "direction" in columns:
        op.drop_column("payment", "direction")

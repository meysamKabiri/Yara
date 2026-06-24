"""add trace_event_counter table

Revision ID: 20260624_0003
Revises: 20260624_0002
Create Date: 2026-06-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260624_0003"
down_revision: str | None = "20260624_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trace_event_counter",
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("counter", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("trace_id", name=op.f("pk_trace_event_counter")),
    )


def downgrade() -> None:
    op.drop_table("trace_event_counter")

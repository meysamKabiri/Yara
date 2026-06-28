"""add event_group and event_index to trace_events

Revision ID: 20260624_0002
Revises: 20260624_0001
Create Date: 2026-06-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260624_0002"
down_revision: str | None = "20260624_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trace_events", sa.Column("event_group", sa.String(), nullable=False, server_default="OTHER"))
    op.add_column("trace_events", sa.Column("event_index", sa.Integer(), nullable=False, server_default="0"))
    op.drop_index("ix_trace_events_trace_id_ts", table_name="trace_events")
    op.create_index("ix_trace_events_trace_id_idx", "trace_events", ["trace_id", "event_index"])
    op.alter_column("trace_events", "event_group", server_default=None)
    op.alter_column("trace_events", "event_index", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_trace_events_trace_id_idx", table_name="trace_events")
    op.create_index("ix_trace_events_trace_id_ts", "trace_events", ["trace_id", "created_at"])
    op.drop_column("trace_events", "event_index")
    op.drop_column("trace_events", "event_group")

"""create next_trace_event_index PostgreSQL function

Revision ID: 20260624_0004
Revises: 20260624_0003
Create Date: 2026-06-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260624_0004"
down_revision: str | None = "20260624_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION next_trace_event_index(trace_id TEXT)
        RETURNS INTEGER
        LANGUAGE SQL
        AS $$
          INSERT INTO trace_event_counter (trace_id, counter)
          VALUES (trace_id, 1)
          ON CONFLICT (trace_id)
          DO UPDATE SET counter = trace_event_counter.counter + 1
          RETURNING counter;
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS next_trace_event_index(TEXT)")

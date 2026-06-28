"""replace next_trace_event_index with PL/pgSQL version

Revision ID: 20260624_0005
Revises: 20260624_0004
Create Date: 2026-06-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260624_0005"
down_revision: str | None = "20260624_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS next_trace_event_index(TEXT)")
    op.execute(
        """
        CREATE FUNCTION next_trace_event_index(p_trace_id TEXT)
        RETURNS INTEGER
        LANGUAGE plpgsql
        AS $$
        DECLARE next_val INTEGER;
        BEGIN
          INSERT INTO trace_event_counter(trace_id, counter)
          VALUES (p_trace_id, 0)
          ON CONFLICT (trace_id) DO NOTHING;

          UPDATE trace_event_counter
          SET counter = counter + 1
          WHERE trace_id = p_trace_id
          RETURNING counter INTO next_val;

          RETURN next_val;
        END;
        $$;
        """
    )


def downgrade() -> None:
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

"""harden natural input job trace integrity

Revision ID: 20260622_0002
Revises: 20260622_0001
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260622_0002"
down_revision: str | None = "20260622_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "natural_input_jobs" not in set(inspector.get_table_names()):
        return

    jobs = sa.table(
        "natural_input_jobs",
        sa.column("id", sa.Integer()),
        sa.column("job_id", sa.String()),
        sa.column("trace_id", sa.String()),
    )
    rows = bind.execute(sa.select(jobs.c.id, jobs.c.job_id, jobs.c.trace_id)).mappings()
    seen: set[str] = set()
    for row in rows:
        trace_id = row["trace_id"] or f"trace-{row['job_id']}"
        if trace_id in seen:
            trace_id = f"trace-{row['job_id']}"
        seen.add(trace_id)
        bind.execute(jobs.update().where(jobs.c.id == row["id"]).values(trace_id=trace_id))

    indexes = {index["name"] for index in inspector.get_indexes("natural_input_jobs")}
    if "ix_natural_input_jobs_trace_id" in indexes:
        op.drop_index("ix_natural_input_jobs_trace_id", table_name="natural_input_jobs")
    with op.batch_alter_table("natural_input_jobs") as batch_op:
        batch_op.alter_column("trace_id", existing_type=sa.String(length=64), nullable=False)
        batch_op.create_index("ix_natural_input_jobs_trace_id", ["trace_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "natural_input_jobs" not in set(inspector.get_table_names()):
        return

    indexes = {index["name"] for index in inspector.get_indexes("natural_input_jobs")}
    if "ix_natural_input_jobs_trace_id" in indexes:
        op.drop_index("ix_natural_input_jobs_trace_id", table_name="natural_input_jobs")
    with op.batch_alter_table("natural_input_jobs") as batch_op:
        batch_op.alter_column("trace_id", existing_type=sa.String(length=64), nullable=True)
        batch_op.create_index("ix_natural_input_jobs_trace_id", ["trace_id"])

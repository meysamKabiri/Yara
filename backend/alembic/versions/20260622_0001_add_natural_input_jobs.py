"""add natural input jobs

Revision ID: 20260622_0001
Revises: 20260619_0002
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260622_0001"
down_revision: str | None = "20260619_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "natural_input_jobs" in tables:
        return

    op.create_table(
        "natural_input_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_natural_input_jobs_job_id", "natural_input_jobs", ["job_id"])
    op.create_index("ix_natural_input_jobs_project_id", "natural_input_jobs", ["project_id"])
    op.create_index("ix_natural_input_jobs_trace_id", "natural_input_jobs", ["trace_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "natural_input_jobs" not in set(inspector.get_table_names()):
        return

    indexes = {index["name"] for index in inspector.get_indexes("natural_input_jobs")}
    if "ix_natural_input_jobs_trace_id" in indexes:
        op.drop_index("ix_natural_input_jobs_trace_id", table_name="natural_input_jobs")
    if "ix_natural_input_jobs_project_id" in indexes:
        op.drop_index("ix_natural_input_jobs_project_id", table_name="natural_input_jobs")
    if "ix_natural_input_jobs_job_id" in indexes:
        op.drop_index("ix_natural_input_jobs_job_id", table_name="natural_input_jobs")
    op.drop_table("natural_input_jobs")

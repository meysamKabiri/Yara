"""add reconciliation monitoring

Revision ID: 20260628_0004
Revises: 20260628_0003
Create Date: 2026-06-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260628_0004"
down_revision: str | None = "20260628_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    project_columns = _columns("project")
    if "reconciliation_status" not in project_columns:
        op.add_column(
            "project",
            sa.Column("reconciliation_status", sa.String(length=30), nullable=False, server_default="OK"),
        )
    if "last_reconciled_at" not in project_columns:
        op.add_column("project", sa.Column("last_reconciled_at", sa.DateTime(), nullable=True))

    tables = _tables()
    if "reconciliation_event" not in tables:
        op.create_table(
            "reconciliation_event",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("drift_detected", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_reconciliation_event_project_id", "reconciliation_event", ["project_id"])

    if "dead_letter_job" not in tables:
        op.create_table(
            "dead_letter_job",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.String(length=64), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("error_trace", sa.Text(), nullable=False),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source", sa.String(length=80), nullable=False, server_default="natural_input"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_dead_letter_job_job_id", "dead_letter_job", ["job_id"])
        op.create_index("ix_dead_letter_job_project_id", "dead_letter_job", ["project_id"])


def downgrade() -> None:
    tables = _tables()
    if "dead_letter_job" in tables:
        op.drop_index("ix_dead_letter_job_project_id", table_name="dead_letter_job")
        op.drop_index("ix_dead_letter_job_job_id", table_name="dead_letter_job")
        op.drop_table("dead_letter_job")
    if "reconciliation_event" in tables:
        op.drop_index("ix_reconciliation_event_project_id", table_name="reconciliation_event")
        op.drop_table("reconciliation_event")
    project_columns = _columns("project")
    if "last_reconciled_at" in project_columns:
        op.drop_column("project", "last_reconciled_at")
    if "reconciliation_status" in project_columns:
        op.drop_column("project", "reconciliation_status")

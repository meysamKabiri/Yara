"""add interpretation feedback capture

Revision ID: 20260629_0002
Revises: 20260629_0001
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260629_0002"
down_revision: str | None = "20260629_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "interpretation_feedback" in _tables():
        return

    op.create_table(
        "interpretation_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("raw_input", sa.Text(), nullable=False),
        sa.Column("system_output", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("user_final_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_types", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("correction_source", sa.String(length=30), nullable=False),
        sa.Column("submission_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_hash", name="uq_interpretation_feedback_submission_hash"),
    )
    op.create_index(
        "ix_interpretation_feedback_project_id",
        "interpretation_feedback",
        ["project_id"],
    )
    op.create_index(
        "ix_interpretation_feedback_trace_id",
        "interpretation_feedback",
        ["trace_id"],
    )


def downgrade() -> None:
    if "interpretation_feedback" not in _tables():
        return
    op.drop_index("ix_interpretation_feedback_trace_id", table_name="interpretation_feedback")
    op.drop_index("ix_interpretation_feedback_project_id", table_name="interpretation_feedback")
    op.drop_table("interpretation_feedback")

"""Add work log period metadata.

Revision ID: 20260627_0001
Revises: 20260624_0006
Create Date: 2026-06-27
"""

from alembic import op
import sqlalchemy as sa


revision: str = "20260627_0001"
down_revision: str | None = "20260624_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("worklog", sa.Column("period_label", sa.String(length=120), nullable=True))
    op.add_column("worklog", sa.Column("source_pending_interpretation_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_worklog_source_pending_interpretation_id",
        "worklog",
        ["source_pending_interpretation_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_worklog_source_pending_id",
        "worklog",
        "pendinginterpretation",
        ["source_pending_interpretation_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_worklog_source_pending_id",
        "worklog",
        type_="foreignkey",
    )
    op.drop_index("ix_worklog_source_pending_interpretation_id", table_name="worklog")
    op.drop_column("worklog", "source_pending_interpretation_id")
    op.drop_column("worklog", "period_label")

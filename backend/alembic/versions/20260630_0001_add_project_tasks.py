"""add project task assignment suggestions

Revision ID: 20260630_0001
Revises: 20260629_0002
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260630_0001"
down_revision: str | None = "20260629_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "project_task" in _tables():
        return

    op.create_table(
        "project_task",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.Column("assignee_suggestion", sa.JSON(), nullable=True),
        sa.Column("suggestion_source", sa.String(length=30), nullable=False, server_default="none"),
        sa.Column("assignment_status", sa.String(length=30), nullable=False, server_default="unassigned"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assignee_id"], ["worker.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_task_project_id", "project_task", ["project_id"])
    op.create_index("ix_project_task_assignee_id", "project_task", ["assignee_id"])


def downgrade() -> None:
    if "project_task" not in _tables():
        return
    op.drop_index("ix_project_task_assignee_id", table_name="project_task")
    op.drop_index("ix_project_task_project_id", table_name="project_task")
    op.drop_table("project_task")

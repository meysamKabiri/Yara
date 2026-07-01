"""persist task orchestrator output

Revision ID: 20260630_0003
Revises: 20260630_0002
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260630_0003"
down_revision: str | None = "20260630_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing = _columns("project_task")
    if not existing:
        return
    if "description" not in existing:
        op.add_column("project_task", sa.Column("description", sa.Text(), nullable=True))
    if "status" not in existing:
        op.add_column("project_task", sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"))
    if "confidence" not in existing:
        op.add_column("project_task", sa.Column("confidence", sa.Float(), nullable=True))
    if "final_task_object" not in existing:
        op.add_column("project_task", sa.Column("final_task_object", sa.JSON(), nullable=True))


def downgrade() -> None:
    existing = _columns("project_task")
    if "final_task_object" in existing:
        op.drop_column("project_task", "final_task_object")
    if "confidence" in existing:
        op.drop_column("project_task", "confidence")
    if "status" in existing:
        op.drop_column("project_task", "status")
    if "description" in existing:
        op.drop_column("project_task", "description")

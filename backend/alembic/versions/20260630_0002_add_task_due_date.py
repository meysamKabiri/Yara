"""add task due date extraction fields

Revision ID: 20260630_0002
Revises: 20260630_0001
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260630_0002"
down_revision: str | None = "20260630_0001"
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
    if "due_date" not in existing:
        op.add_column("project_task", sa.Column("due_date", sa.Date(), nullable=True))
    if "due_date_confidence" not in existing:
        op.add_column("project_task", sa.Column("due_date_confidence", sa.Float(), nullable=True))
    if "due_date_source" not in existing:
        op.add_column("project_task", sa.Column("due_date_source", sa.String(length=50), nullable=True))


def downgrade() -> None:
    existing = _columns("project_task")
    if "due_date_source" in existing:
        op.drop_column("project_task", "due_date_source")
    if "due_date_confidence" in existing:
        op.drop_column("project_task", "due_date_confidence")
    if "due_date" in existing:
        op.drop_column("project_task", "due_date")

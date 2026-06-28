"""Add confirmed record void and correction metadata.

Revision ID: 20260627_0002
Revises: 20260627_0001
Create Date: 2026-06-27
"""

from alembic import op
import sqlalchemy as sa


revision: str = "20260627_0002"
down_revision: str | None = "20260627_0001"
branch_labels = None
depends_on = None


TABLES = ("payment", "invoice", "worklog", "historyentry")


def upgrade() -> None:
    for table in TABLES:
        if table == "payment":
            op.add_column(table, sa.Column("description", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("is_voided", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.add_column(table, sa.Column("void_reason", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("voided_at", sa.DateTime(), nullable=True))
        op.add_column(table, sa.Column("correction_note", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("corrected_at", sa.DateTime(), nullable=True))
        op.alter_column(table, "is_voided", server_default=None)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_column(table, "corrected_at")
        op.drop_column(table, "correction_note")
        op.drop_column(table, "voided_at")
        op.drop_column(table, "void_reason")
        op.drop_column(table, "is_voided")
        if table == "payment":
            op.drop_column(table, "description")

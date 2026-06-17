"""add worker state history

Revision ID: 20260617_0004
Revises: 20260617_0003
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260617_0004"
down_revision: str | None = "20260617_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workerstate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("DAILY", "SKILLED", "VENDOR", "CLIENT", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("total_days_worked", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_quantity", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("financial_balance", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_workerstate_project_id_project"),
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["worker.id"],
            name=op.f("fk_workerstate_worker_id_worker"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workerstate")),
    )
    op.create_index(op.f("ix_workerstate_project_id"), "workerstate", ["project_id"])
    op.create_index(op.f("ix_workerstate_worker_id"), "workerstate", ["worker_id"])

    op.create_table(
        "historyentry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("worker_state_id", sa.Integer(), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column(
            "change_type",
            sa.Enum("WORK", "PAYMENT", "INVOICE", "SETUP", "NOTE", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("delta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_historyentry_project_id_project"),
        ),
        sa.ForeignKeyConstraint(
            ["worker_state_id"],
            ["workerstate.id"],
            name=op.f("fk_historyentry_worker_state_id_workerstate"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_historyentry")),
    )
    op.create_index(op.f("ix_historyentry_project_id"), "historyentry", ["project_id"])
    op.create_index(
        op.f("ix_historyentry_worker_state_id"),
        "historyentry",
        ["worker_state_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_historyentry_worker_state_id"), table_name="historyentry")
    op.drop_index(op.f("ix_historyentry_project_id"), table_name="historyentry")
    op.drop_table("historyentry")
    op.drop_index(op.f("ix_workerstate_worker_id"), table_name="workerstate")
    op.drop_index(op.f("ix_workerstate_project_id"), table_name="workerstate")
    op.drop_table("workerstate")

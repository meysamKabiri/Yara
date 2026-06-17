"""add construction operations

Revision ID: 20260617_0003
Revises: 20260617_0002
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260617_0003"
down_revision: str | None = "20260617_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "DAILY_WORKER",
                "SKILLED_WORKER",
                "VENDOR",
                "CLIENT",
                native_enum=False,
                length=30,
            ),
            nullable=False,
        ),
        sa.Column("role_detail", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("account_number", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_worker_project_id_project"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_worker")),
    )
    op.create_index(op.f("ix_worker_project_id"), "worker", ["project_id"], unique=False)

    op.create_table(
        "worklog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column(
            "unit",
            sa.Enum("meter", "day", "item", "project", "custom", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("rate_per_unit", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_worklog_project_id_project"),
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["worker.id"],
            name=op.f("fk_worklog_worker_id_worker"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_worklog")),
    )
    op.create_index(op.f("ix_worklog_project_id"), "worklog", ["project_id"], unique=False)
    op.create_index(op.f("ix_worklog_worker_id"), "worklog", ["worker_id"], unique=False)

    op.create_table(
        "invoice",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("OPEN", "PARTIAL", "PAID", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_invoice_project_id_project"),
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["worker.id"],
            name=op.f("fk_invoice_vendor_id_worker"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice")),
    )
    op.create_index(op.f("ix_invoice_project_id"), "invoice", ["project_id"], unique=False)
    op.create_index(op.f("ix_invoice_vendor_id"), "invoice", ["vendor_id"], unique=False)

    op.create_table(
        "payment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("related_invoice_id", sa.Integer(), nullable=True),
        sa.Column(
            "type",
            sa.Enum("CASH", "BANK_TRANSFER", "OTHER", native_enum=False, length=30),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["worker.id"],
            name=op.f("fk_payment_entity_id_worker"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_payment_project_id_project"),
        ),
        sa.ForeignKeyConstraint(
            ["related_invoice_id"],
            ["invoice.id"],
            name=op.f("fk_payment_related_invoice_id_invoice"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment")),
    )
    op.create_index(op.f("ix_payment_entity_id"), "payment", ["entity_id"], unique=False)
    op.create_index(op.f("ix_payment_project_id"), "payment", ["project_id"], unique=False)
    op.create_index(
        op.f("ix_payment_related_invoice_id"),
        "payment",
        ["related_invoice_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_payment_related_invoice_id"), table_name="payment")
    op.drop_index(op.f("ix_payment_project_id"), table_name="payment")
    op.drop_index(op.f("ix_payment_entity_id"), table_name="payment")
    op.drop_table("payment")
    op.drop_index(op.f("ix_invoice_vendor_id"), table_name="invoice")
    op.drop_index(op.f("ix_invoice_project_id"), table_name="invoice")
    op.drop_table("invoice")
    op.drop_index(op.f("ix_worklog_worker_id"), table_name="worklog")
    op.drop_index(op.f("ix_worklog_project_id"), table_name="worklog")
    op.drop_table("worklog")
    op.drop_index(op.f("ix_worker_project_id"), table_name="worker")
    op.drop_table("worker")

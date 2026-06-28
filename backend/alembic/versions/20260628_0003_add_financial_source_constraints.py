"""add financial source constraints

Revision ID: 20260628_0003
Revises: 20260628_0002
Create Date: 2026-06-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260628_0003"
down_revision: str | None = "20260628_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _constraints(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {constraint["name"] for constraint in inspector.get_unique_constraints(table_name)}


def upgrade() -> None:
    payment_columns = _columns("payment")
    invoice_columns = _columns("invoice")

    if "source_pending_interpretation_id" not in payment_columns:
        op.add_column(
            "payment",
            sa.Column("source_pending_interpretation_id", sa.Integer(), nullable=True),
        )
        op.create_index(
            "ix_payment_source_pending_interpretation_id",
            "payment",
            ["source_pending_interpretation_id"],
        )
    if "source_pending_interpretation_id" not in invoice_columns:
        op.add_column(
            "invoice",
            sa.Column("source_pending_interpretation_id", sa.Integer(), nullable=True),
        )
        op.create_index(
            "ix_invoice_source_pending_interpretation_id",
            "invoice",
            ["source_pending_interpretation_id"],
        )

    payment_constraints = _constraints("payment")
    invoice_constraints = _constraints("invoice")
    if "uq_payment_source_pending_interpretation" not in payment_constraints:
        op.create_unique_constraint(
            "uq_payment_source_pending_interpretation",
            "payment",
            ["source_pending_interpretation_id"],
        )
    if "uq_invoice_source_pending_interpretation" not in invoice_constraints:
        op.create_unique_constraint(
            "uq_invoice_source_pending_interpretation",
            "invoice",
            ["source_pending_interpretation_id"],
        )
    op.create_foreign_key(
        "fk_payment_source_pending_interpretation",
        "payment",
        "pendinginterpretation",
        ["source_pending_interpretation_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_invoice_source_pending_interpretation",
        "invoice",
        "pendinginterpretation",
        ["source_pending_interpretation_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_invoice_source_pending_interpretation", "invoice", type_="foreignkey")
    op.drop_constraint("fk_payment_source_pending_interpretation", "payment", type_="foreignkey")
    op.drop_constraint("uq_invoice_source_pending_interpretation", "invoice", type_="unique")
    op.drop_constraint("uq_payment_source_pending_interpretation", "payment", type_="unique")
    op.drop_index("ix_invoice_source_pending_interpretation_id", table_name="invoice")
    op.drop_index("ix_payment_source_pending_interpretation_id", table_name="payment")
    op.drop_column("invoice", "source_pending_interpretation_id")
    op.drop_column("payment", "source_pending_interpretation_id")

"""add pending interpretations

Revision ID: 20260617_0007
Revises: 20260617_0006
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260617_0007"
down_revision: str | None = "20260617_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pendinginterpretation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("raw_input_text", sa.Text(), nullable=False),
        sa.Column("canonical_event_type", sa.String(length=50), nullable=False),
        sa.Column("semantic_action", sa.String(length=100), nullable=False),
        sa.Column("suggested_entity_id", sa.Integer(), nullable=True),
        sa.Column("matched_input_text", sa.String(length=255), nullable=True),
        sa.Column("extracted_entities", sa.JSON(), nullable=True),
        sa.Column("extracted_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("extracted_quantity", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("payment_method", sa.String(length=50), nullable=True),
        sa.Column(
            "financial_direction",
            sa.Enum("INCOMING", "OUTGOING", "DEBT", "DEFERRED", native_enum=False, length=20),
            nullable=True,
        ),
        sa.Column("due_date", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("semantic_explanation", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING", "CONFIRMED", "EDITED", "DISCARDED", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_pendinginterpretation_project_id_project"),
        ),
        sa.ForeignKeyConstraint(
            ["suggested_entity_id"],
            ["worker.id"],
            name=op.f("fk_pendinginterpretation_suggested_entity_id_worker"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pendinginterpretation")),
    )
    op.create_index(
        op.f("ix_pendinginterpretation_project_id"),
        "pendinginterpretation",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pendinginterpretation_project_id"), table_name="pendinginterpretation")
    op.drop_table("pendinginterpretation")

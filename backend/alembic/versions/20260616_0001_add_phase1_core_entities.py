"""add phase1 core entities

Revision ID: 20260616_0001
Revises:
Create Date: 2026-06-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260616_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project")),
    )
    op.create_table(
        "rawentry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "PROCESSED", "FAILED", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_rawentry_project_id_project"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rawentry")),
    )
    op.create_index(op.f("ix_rawentry_project_id"), "rawentry", ["project_id"], unique=False)
    op.create_table(
        "extractedevent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("raw_entry_id", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("MONEY_IN", "MONEY_OUT", "PURCHASE", "NOTE", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("counterparty_name", sa.String(length=255), nullable=True),
        sa.Column(
            "counterparty_type",
            sa.Enum("PERSON", "VENDOR", "CLIENT", "UNKNOWN", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING", "CONFIRMED", "DISCARDED", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_extractedevent_project_id_project"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_entry_id"],
            ["rawentry.id"],
            name=op.f("fk_extractedevent_raw_entry_id_rawentry"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extractedevent")),
    )
    op.create_index(
        op.f("ix_extractedevent_project_id"),
        "extractedevent",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_extractedevent_raw_entry_id"),
        "extractedevent",
        ["raw_entry_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_extractedevent_raw_entry_id"), table_name="extractedevent")
    op.drop_index(op.f("ix_extractedevent_project_id"), table_name="extractedevent")
    op.drop_table("extractedevent")
    op.drop_index(op.f("ix_rawentry_project_id"), table_name="rawentry")
    op.drop_table("rawentry")
    op.drop_table("project")

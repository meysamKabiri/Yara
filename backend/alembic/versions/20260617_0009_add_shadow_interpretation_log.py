"""add shadow interpretation log

Revision ID: 20260617_0009
Revises: 20260617_0008
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260617_0009"
down_revision: str | None = "20260617_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shadow_interpretation_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("legacy_json", sa.JSON(), nullable=False),
        sa.Column("shadow_json", sa.JSON(), nullable=False),
        sa.Column("diff_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_shadow_interpretation_log_project_id_project"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shadow_interpretation_log")),
    )
    op.create_index(
        op.f("ix_shadow_interpretation_log_project_id"),
        "shadow_interpretation_log",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_shadow_interpretation_log_project_id"),
        table_name="shadow_interpretation_log",
    )
    op.drop_table("shadow_interpretation_log")

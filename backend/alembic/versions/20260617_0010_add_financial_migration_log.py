"""add financial migration log

Revision ID: 20260617_0010
Revises: 20260617_0009
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260617_0010"
down_revision: str | None = "20260617_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("financial_migration_log"):
        op.create_table(
            "financial_migration_log",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("input_text", sa.Text(), nullable=False),
            sa.Column("legacy_json", sa.JSON(), nullable=False),
            sa.Column("shadow_json", sa.JSON(), nullable=False),
            sa.Column("chosen_system", sa.String(length=20), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["project.id"],
                name=op.f("fk_financial_migration_log_project_id_project"),
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_migration_log")),
        )
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("financial_migration_log")}
    index_name = op.f("ix_financial_migration_log_project_id")
    if index_name not in indexes:
        op.create_index(
            index_name,
            "financial_migration_log",
            ["project_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("financial_migration_log"):
        indexes = {index["name"] for index in inspector.get_indexes("financial_migration_log")}
        index_name = op.f("ix_financial_migration_log_project_id")
        if index_name in indexes:
            op.drop_index(index_name, table_name="financial_migration_log")
        op.drop_table("financial_migration_log")

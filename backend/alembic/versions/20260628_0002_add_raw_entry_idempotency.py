"""add raw entry idempotency

Revision ID: 20260628_0002
Revises: 20260628_0001
Create Date: 2026-06-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260628_0002"
down_revision: str | None = "20260628_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("rawentry")}
    if "job_id" not in columns:
        op.add_column("rawentry", sa.Column("job_id", sa.String(length=64), nullable=True))
    if "idempotency_key" not in columns:
        op.add_column("rawentry", sa.Column("idempotency_key", sa.String(length=128), nullable=True))

    indexes = {index["name"] for index in inspector.get_indexes("rawentry")}
    if "ix_rawentry_job_id" not in indexes:
        op.create_index("ix_rawentry_job_id", "rawentry", ["job_id"])

    constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("rawentry")}
    if "uq_rawentry_project_idempotency_key" not in constraints:
        op.create_unique_constraint(
            "uq_rawentry_project_idempotency_key",
            "rawentry",
            ["project_id", "idempotency_key"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("rawentry")}
    if "uq_rawentry_project_idempotency_key" in constraints:
        op.drop_constraint("uq_rawentry_project_idempotency_key", "rawentry", type_="unique")

    indexes = {index["name"] for index in inspector.get_indexes("rawentry")}
    if "ix_rawentry_job_id" in indexes:
        op.drop_index("ix_rawentry_job_id", table_name="rawentry")

    columns = {column["name"] for column in inspector.get_columns("rawentry")}
    if "idempotency_key" in columns:
        op.drop_column("rawentry", "idempotency_key")
    if "job_id" in columns:
        op.drop_column("rawentry", "job_id")

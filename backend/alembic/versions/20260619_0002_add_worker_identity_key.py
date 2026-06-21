"""add worker identity key

Revision ID: 20260619_0002
Revises: 20260619_0001
Create Date: 2026-06-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_0002"
down_revision: str | None = "20260619_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("worker")}
    indexes = {index["name"] for index in inspector.get_indexes("worker")}

    if "identity_key" not in columns:
        op.add_column("worker", sa.Column("identity_key", sa.String(length=255), nullable=True))
    if "ix_worker_project_identity_key" not in indexes:
        op.create_index(
            "ix_worker_project_identity_key",
            "worker",
            ["project_id", "identity_key"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("worker")}
    indexes = {index["name"] for index in inspector.get_indexes("worker")}

    if "ix_worker_project_identity_key" in indexes:
        op.drop_index("ix_worker_project_identity_key", table_name="worker")
    if "identity_key" in columns:
        op.drop_column("worker", "identity_key")

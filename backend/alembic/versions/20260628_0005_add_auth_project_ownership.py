"""add auth project ownership

Revision ID: 20260628_0005
Revises: 20260628_0004
Create Date: 2026-06-28
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op


revision: str = "20260628_0005"
down_revision: str | None = "20260628_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if "users" not in _tables():
        op.create_table(
            "users",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email"),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    project_columns = _columns("project")
    if "owner_id" not in project_columns:
        op.add_column("project", sa.Column("owner_id", sa.Uuid(), nullable=True))
        op.create_index("ix_project_owner_id", "project", ["owner_id"])
        op.execute(
            sa.text(
                """
                INSERT INTO users (id, email, password_hash)
                VALUES (:id, :email, :password_hash)
                ON CONFLICT (email) DO NOTHING
                """
            ).bindparams(
                sa.bindparam("id", LEGACY_USER_ID, type_=sa.Uuid()),
                sa.bindparam("email", "legacy-owner@yara.local"),
                sa.bindparam("password_hash", "pbkdf2_sha256$260000$legacy$legacy"),
            )
        )
        op.execute(
            sa.text("UPDATE project SET owner_id = :id WHERE owner_id IS NULL").bindparams(
                sa.bindparam("id", LEGACY_USER_ID, type_=sa.Uuid())
            )
        )
        op.alter_column("project", "owner_id", nullable=False)
        op.create_foreign_key("fk_project_owner_id_users", "project", "users", ["owner_id"], ["id"])


def downgrade() -> None:
    project_columns = _columns("project")
    if "owner_id" in project_columns:
        op.drop_constraint("fk_project_owner_id_users", "project", type_="foreignkey")
        op.drop_index("ix_project_owner_id", table_name="project")
        op.drop_column("project", "owner_id")
    if "users" in _tables():
        op.drop_index("ix_users_email", table_name="users")
        op.drop_table("users")

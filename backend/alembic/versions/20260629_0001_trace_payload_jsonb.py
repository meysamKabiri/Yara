"""store trace event payloads as JSONB

Revision ID: 20260629_0001
Revises: 20260628_0005
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260629_0001"
down_revision: str | None = "20260628_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "trace_events",
        "payload",
        existing_type=sa.JSON(),
        type_=postgresql.JSONB(),
        postgresql_using="payload::jsonb",
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "trace_events",
        "payload",
        existing_type=postgresql.JSONB(),
        type_=sa.JSON(),
        existing_nullable=True,
    )

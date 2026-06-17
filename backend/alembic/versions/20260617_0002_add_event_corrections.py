"""add event corrections

Revision ID: 20260617_0002
Revises: 20260616_0001
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260617_0002"
down_revision: str | None = "20260616_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("extractedevent", sa.Column("ai_confidence", sa.Float(), nullable=True))
    op.add_column(
        "extractedevent",
        sa.Column("user_edited", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("extractedevent", sa.Column("updated_by_user_at", sa.DateTime(), nullable=True))
    op.create_table(
        "eventcorrection",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("field_name", sa.String(length=100), nullable=False),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["extractedevent.id"],
            name=op.f("fk_eventcorrection_event_id_extractedevent"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eventcorrection")),
    )
    op.create_index(
        op.f("ix_eventcorrection_event_id"),
        "eventcorrection",
        ["event_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_eventcorrection_event_id"), table_name="eventcorrection")
    op.drop_table("eventcorrection")
    op.drop_column("extractedevent", "updated_by_user_at")
    op.drop_column("extractedevent", "user_edited")
    op.drop_column("extractedevent", "ai_confidence")

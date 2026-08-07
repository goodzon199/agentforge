"""conversation mode (human takeover) + company public_token (web-chat)

Revision ID: a1b2c3d4e5f8
Revises: a1b2c3d4e5f7
Create Date: 2026-08-07 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f8"
down_revision: Union[str, None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conversation_mode = sa.Enum(
        "ai_active", "human_active", "paused", "closed", name="conversation_mode"
    )
    conversation_mode.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "conversations",
        sa.Column(
            "mode",
            conversation_mode,
            nullable=False,
            server_default="ai_active",
        ),
    )
    op.add_column(
        "companies",
        sa.Column("public_token", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_companies_public_token", "companies", ["public_token"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_companies_public_token", table_name="companies")
    op.drop_column("companies", "public_token")
    op.drop_column("conversations", "mode")
    op.execute("DROP TYPE IF EXISTS conversation_mode")

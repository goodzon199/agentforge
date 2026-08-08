"""llm_usage: add status + duration_ms (hotfix 3.4.1)

Revision ID: a1b2c3d4e5fd
Revises: a1b2c3d4e5fc
Create Date: 2026-08-08 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5fd"
down_revision: Union[str, None] = "a1b2c3d4e5fc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_usage",
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="ok"
        ),
    )
    op.add_column(
        "llm_usage",
        sa.Column(
            "duration_ms", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_column("llm_usage", "duration_ms")
    op.drop_column("llm_usage", "status")

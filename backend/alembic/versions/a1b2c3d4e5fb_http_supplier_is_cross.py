"""http supplier adapter: is_cross flag on supplier offers

Revision ID: a1b2c3d4e5fb
Revises: a1b2c3d4e5fa
Create Date: 2026-08-07 19:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5fb"
down_revision: Union[str, None] = "a1b2c3d4e5fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "supplier_offers",
        sa.Column(
            "is_cross",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("supplier_offers", "is_cross")

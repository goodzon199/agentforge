"""pricing engine: quote columns + company pricing settings

Revision ID: 7f3b9c2d4e5a
Revises: c37f28d9a4b1
Create Date: 2026-08-06 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7f3b9c2d4e5a"
down_revision: Union[str, None] = "c37f28d9a4b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Customer-facing price stamped on each offer by the pricing engine.
    op.add_column(
        "supplier_offers",
        sa.Column("customer_price", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "supplier_offers",
        sa.Column("total_price", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "supplier_offers",
        sa.Column("margin_percent", sa.Numeric(5, 2), nullable=True),
    )
    # Per-company pricing overrides (e.g. {"pricing": {"margin_percent": 25}}).
    op.add_column(
        "companies",
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("companies", "settings")
    op.drop_column("supplier_offers", "margin_percent")
    op.drop_column("supplier_offers", "total_price")
    op.drop_column("supplier_offers", "customer_price")

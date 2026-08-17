"""sprint 4.6: order tracking — supplier-side lifecycle on the order

The platform now keeps watching a purchased order after it is placed: the
aggregate supplier-side state (accepted → assembling → shipped → arrived →
handed_over) lives on ``orders.tracking_status`` and is recomputed from the
fulfillment lines' supplier_status. Managers hand the order over to the
customer; the agent may notify the customer when it arrives.

Revision ID: a1b2c3d4e612
Revises: a1b2c3d4e611
Create Date: 2026-08-13 20:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e612"
down_revision: str | None = "a1b2c3d4e611"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "tracking_status",
            sa.String(24),
            nullable=False,
            server_default="pending",
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "tracking_status")

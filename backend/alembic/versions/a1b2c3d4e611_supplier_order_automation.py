"""sprint 4.5: supplier order automation — external order tracking

After the customer accepts a quote and a manager converts it into an order,
the platform asks a human to approve the actual purchase (send_supplier_order
is HIGH risk). Once approved, the supplier adapter places the order and each
fulfillment line carries the supplier's tracking id and its supplier-side
status so the order can be tracked and the customer notified when it arrives.

Revision ID: a1b2c3d4e611
Revises: c3d4e5f612
Create Date: 2026-08-13 18:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e611"
down_revision: str | None = "c3d4e5f612"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "supplier_fulfillments",
        sa.Column("external_order_id", sa.String(80), nullable=True),
    )
    op.add_column(
        "supplier_fulfillments",
        sa.Column("supplier_status", sa.String(40), nullable=True),
    )
    op.add_column(
        "supplier_fulfillments",
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_supplier_fulfillments_external_order_id",
        "supplier_fulfillments",
        ["external_order_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supplier_fulfillments_external_order_id", table_name="supplier_fulfillments"
    )
    op.drop_column("supplier_fulfillments", "ordered_at")
    op.drop_column("supplier_fulfillments", "supplier_status")
    op.drop_column("supplier_fulfillments", "external_order_id")

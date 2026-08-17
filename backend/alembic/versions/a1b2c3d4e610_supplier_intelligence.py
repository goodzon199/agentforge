"""sprint 4.2: supplier intelligence — fulfillment reality + returns attribution

The supplier rating becomes something the system computes, not something a
manager types in. Two raw facts feed the 8 metrics:

1. ``supplier_fulfillments`` — for every order line we snapshot what the
   supplier *promised* (price, delivery days, quantity) and the manager later
   records what *actually* happened (final price, actual delivery days,
   delivered quantity, final status). This is the only source of truth for
   on-time delivery, price-change rate and under-delivery rate.
2. ``part_returns.supplier_id`` — returns are now attributed to a supplier so
   the return rate belongs to the right scoreboard.

Revision ID: a1b2c3d4e610
Revises: a1b2c3d4e609
Create Date: 2026-08-13 14:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e610"
down_revision: str | None = "a1b2c3d4e609"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supplier_fulfillments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "supplier_id",
            sa.Uuid(),
            sa.ForeignKey("suppliers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "offer_id",
            sa.Uuid(),
            sa.ForeignKey("supplier_offers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("article", sa.String(120), nullable=False, server_default=""),
        sa.Column("brand", sa.String(80), nullable=False, server_default=""),
        sa.Column("promised_purchase_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("promised_delivery_days", sa.Integer(), nullable=True),
        sa.Column("quantity_ordered", sa.Integer(), nullable=True),
        sa.Column("actual_purchase_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("actual_delivery_days", sa.Integer(), nullable=True),
        sa.Column("quantity_delivered", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="delivered"),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_supplier_fulfillments_company_id", "supplier_fulfillments", ["company_id"]
    )
    op.create_index(
        "ix_supplier_fulfillments_supplier_id", "supplier_fulfillments", ["supplier_id"]
    )
    op.create_index(
        "ix_supplier_fulfillments_order_id", "supplier_fulfillments", ["order_id"]
    )
    op.create_index(
        "ix_supplier_fulfillments_offer_id", "supplier_fulfillments", ["offer_id"]
    )

    # Returns are now attributed to a supplier (nullable for legacy rows).
    op.add_column(
        "part_returns",
        sa.Column(
            "supplier_id",
            sa.Uuid(),
            sa.ForeignKey("suppliers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_part_returns_supplier_id", "part_returns", ["supplier_id"])


def downgrade() -> None:
    op.drop_index("ix_part_returns_supplier_id", table_name="part_returns")
    op.drop_column("part_returns", "supplier_id")
    op.drop_table("supplier_fulfillments")

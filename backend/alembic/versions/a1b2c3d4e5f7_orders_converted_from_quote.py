"""orders: order converted from an accepted quote

Revision ID: a1b2c3d4e5f7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-07 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    order_status = sa.Enum("new", "confirmed", "paid", "cancelled", name="order_status")

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "part_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("part_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "quote_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("quotes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("order_number", sa.String(40), nullable=False),
        sa.Column("status", order_status, nullable=False, server_default="new"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="RUB"),
        sa.Column("order_total", sa.Numeric(12, 2), nullable=True),
        sa.Column("items", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index("ix_orders_company_id", "orders", ["company_id"])
    op.create_index("ix_orders_conversation_id", "orders", ["conversation_id"])
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_part_request_id", "orders", ["part_request_id"])
    op.create_index("ix_orders_quote_id", "orders", ["quote_id"])
    op.create_index("ix_orders_order_number", "orders", ["order_number"])


def downgrade() -> None:
    op.drop_table("orders")
    op.execute("DROP TYPE IF EXISTS order_status")

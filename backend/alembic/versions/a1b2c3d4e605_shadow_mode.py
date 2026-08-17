"""sprint 3.8.1: shadow mode — companies.shadow_mode + shadow_comparisons

Shadow Mode runs Agentos in parallel with a human manager on the first real
requests: the AI selection is snapshotted, the manager submits their own, the
two are compared (vehicle/part/OEM/offers/price/time) and the AI answer never
reaches the customer.

Revision ID: a1b2c3d4e605
Revises: a1b2c3d4e604
Create Date: 2026-08-12 18:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "a1b2c3d4e605"
down_revision: Union[str, None] = "a1b2c3d4e604"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "shadow_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_table(
        "shadow_comparisons",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "part_request_id",
            UUID(as_uuid=True),
            sa.ForeignKey("part_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("ai_vehicle", sa.Text(), nullable=False, server_default=""),
        sa.Column("ai_part", sa.String(240), nullable=False, server_default=""),
        sa.Column("ai_article", sa.String(120), nullable=False, server_default=""),
        sa.Column("ai_offer_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("ai_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("ai_answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("manager_vehicle", sa.Text(), nullable=False, server_default=""),
        sa.Column("manager_part", sa.String(240), nullable=False, server_default=""),
        sa.Column("manager_article", sa.String(120), nullable=False, server_default=""),
        sa.Column("manager_offer_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("manager_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("manager_reply", sa.Text(), nullable=False, server_default=""),
        sa.Column("vehicle_match", sa.Boolean(), nullable=True),
        sa.Column("part_match", sa.Boolean(), nullable=True),
        sa.Column("oem_match", sa.Boolean(), nullable=True),
        sa.Column("offer_overlap", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("price_delta", sa.Numeric(12, 2), nullable=True),
        sa.Column("time_seconds", sa.Float(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_shadow_comparisons_company_id", "shadow_comparisons", ["company_id"])
    op.create_index("ix_shadow_comparisons_part_request_id", "shadow_comparisons", ["part_request_id"])
    op.create_index("ix_shadow_comparisons_conversation_id", "shadow_comparisons", ["conversation_id"])
    op.create_index("ix_shadow_comparisons_customer_id", "shadow_comparisons", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_shadow_comparisons_customer_id", table_name="shadow_comparisons")
    op.drop_index("ix_shadow_comparisons_conversation_id", table_name="shadow_comparisons")
    op.drop_index("ix_shadow_comparisons_part_request_id", table_name="shadow_comparisons")
    op.drop_index("ix_shadow_comparisons_company_id", table_name="shadow_comparisons")
    op.drop_table("shadow_comparisons")
    op.drop_column("companies", "shadow_mode")

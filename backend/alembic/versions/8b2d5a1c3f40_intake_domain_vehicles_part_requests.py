"""intake domain: vehicles, part_requests

Revision ID: 8b2d5a1c3f40
Revises: f4e7291ad0aa
Create Date: 2026-08-06 15:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "8b2d5a1c3f40"
down_revision: Union[str, None] = "f4e7291ad0aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "vehicles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vin", sa.String(17), nullable=False, server_default=""),
        sa.Column("brand", sa.String(80), nullable=False, server_default=""),
        sa.Column("model", sa.String(120), nullable=False, server_default=""),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("engine", sa.String(80), nullable=False, server_default=""),
        sa.Column("body", sa.String(80), nullable=False, server_default=""),
        sa.Column(
            "registration_number", sa.String(20), nullable=False, server_default=""
        ),
        *_timestamps(),
    )
    op.create_index("ix_vehicles_company_id", "vehicles", ["company_id"])
    op.create_index("ix_vehicles_customer_id", "vehicles", ["customer_id"])

    op.create_table(
        "part_requests",
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
            "vehicle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vehicles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversation_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("intent", sa.String(40), nullable=False, server_default="part_search"),
        sa.Column("part_name", sa.String(240), nullable=False, server_default=""),
        sa.Column("article", sa.String(120), nullable=False, server_default=""),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            sa.Enum(
                "collecting_data",
                "ready_for_search",
                "searching",
                "quoted",
                "approved",
                "completed",
                "cancelled",
                name="part_request_status",
            ),
            nullable=False,
            server_default="collecting_data",
        ),
        sa.Column(
            "missing_fields", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column("structured_data", sa.JSON(), nullable=False, server_default="{}"),
        *_timestamps(),
    )
    op.create_index(
        "ix_part_requests_company_id", "part_requests", ["company_id"]
    )
    op.create_index(
        "ix_part_requests_conversation_id", "part_requests", ["conversation_id"]
    )
    op.create_index(
        "ix_part_requests_customer_id", "part_requests", ["customer_id"]
    )
    op.create_index(
        "ix_part_requests_vehicle_id", "part_requests", ["vehicle_id"]
    )
    op.create_index(
        "ix_part_requests_source_message_id", "part_requests", ["source_message_id"]
    )


def downgrade() -> None:
    op.drop_table("part_requests")
    op.execute("DROP TYPE IF EXISTS part_request_status")
    op.drop_table("vehicles")

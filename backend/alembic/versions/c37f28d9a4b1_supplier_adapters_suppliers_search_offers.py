"""supplier adapters: suppliers, search runs, offers

Revision ID: c37f28d9a4b1
Revises: 8b2d5a1c3f40
Create Date: 2026-08-06 16:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c37f28d9a4b1"
down_revision: Union[str, None] = "8b2d5a1c3f40"
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


def _search_run_status() -> sa.Enum:
    return sa.Enum(
        "running",
        "completed",
        "failed",
        name="supplier_search_status",
    )


def _attempt_status() -> sa.Enum:
    return sa.Enum(
        "pending",
        "succeeded",
        "failed",
        name="supplier_attempt_status",
    )


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("slug", sa.String(180), nullable=False),
        sa.Column("adapter_type", sa.String(40), nullable=False, server_default="mock"),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
        *_timestamps(),
    )
    op.create_index("ix_suppliers_company_id", "suppliers", ["company_id"])
    op.create_index("ix_suppliers_slug", "suppliers", ["slug"])

    op.create_table(
        "supplier_search_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "part_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("part_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status", _search_run_status(), nullable=False, server_default="running"
        ),
        sa.Column("offers_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "suppliers_succeeded", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("suppliers_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(1000), nullable=False, server_default=""),
        sa.Column("structured_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index(
        "ix_supplier_search_runs_part_request_id",
        "supplier_search_runs",
        ["part_request_id"],
    )

    op.create_table(
        "supplier_search_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "search_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("supplier_search_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", _attempt_status(), nullable=False, server_default="pending"),
        sa.Column("offers_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(1000), nullable=False, server_default=""),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index(
        "ix_supplier_search_attempts_search_run_id",
        "supplier_search_attempts",
        ["search_run_id"],
    )
    op.create_index(
        "ix_supplier_search_attempts_supplier_id",
        "supplier_search_attempts",
        ["supplier_id"],
    )

    op.create_table(
        "supplier_offers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "part_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("part_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "search_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("supplier_search_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("brand", sa.String(80), nullable=False, server_default=""),
        sa.Column("article", sa.String(120), nullable=False, server_default=""),
        sa.Column("part_name", sa.String(240), nullable=False, server_default=""),
        sa.Column("purchase_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("delivery_days", sa.Integer(), nullable=True),
        *_timestamps(),
    )
    op.create_index(
        "ix_supplier_offers_part_request_id", "supplier_offers", ["part_request_id"]
    )
    op.create_index(
        "ix_supplier_offers_search_run_id", "supplier_offers", ["search_run_id"]
    )
    op.create_index(
        "ix_supplier_offers_supplier_id", "supplier_offers", ["supplier_id"]
    )


def downgrade() -> None:
    op.drop_table("supplier_offers")
    op.drop_table("supplier_search_attempts")
    op.execute("DROP TYPE IF EXISTS supplier_attempt_status")
    op.drop_table("supplier_search_runs")
    op.execute("DROP TYPE IF EXISTS supplier_search_status")
    op.drop_table("suppliers")

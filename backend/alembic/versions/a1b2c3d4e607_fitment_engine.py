"""sprint 4.0: fitment engine — catalog fitment, cross references, returns, evidence

The Parts Intelligence layer: tables that let the system compute a real
``fitment_confidence`` (from catalog/OEM fitment + cross references + order
history + manager confirmations + returns) instead of reusing the intent
confidence as a fitment proxy.

Revision ID: a1b2c3d4e607
Revises: a1b2c3d4e606
Create Date: 2026-08-13 11:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e607"
down_revision: str | None = "a1b2c3d4e606"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_fitments",
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
        sa.Column("article", sa.String(120), nullable=False),
        sa.Column("brand", sa.String(80), nullable=False, server_default=""),
        sa.Column("part_name", sa.String(240), nullable=False, server_default=""),
        sa.Column("vehicle_brand", sa.String(80), nullable=False, server_default=""),
        sa.Column("vehicle_model", sa.String(120), nullable=False, server_default=""),
        sa.Column("year_from", sa.Integer(), nullable=True),
        sa.Column("year_to", sa.Integer(), nullable=True),
        sa.Column("engine", sa.String(80), nullable=False, server_default=""),
        sa.Column("source", sa.String(40), nullable=False, server_default="catalog"),
        sa.Column("oem_article", sa.String(120), nullable=False, server_default=""),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0.9000"),
    )
    op.create_index("ix_catalog_fitments_company_id", "catalog_fitments", ["company_id"])
    op.create_index("ix_catalog_fitments_article", "catalog_fitments", ["article"])

    op.create_table(
        "cross_references",
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
        sa.Column("source_article", sa.String(120), nullable=False),
        sa.Column("source_brand", sa.String(80), nullable=False, server_default=""),
        sa.Column("target_article", sa.String(120), nullable=False),
        sa.Column("target_brand", sa.String(80), nullable=False, server_default=""),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0.8000"),
        sa.Column("source", sa.String(40), nullable=False, server_default="catalog"),
    )
    op.create_index("ix_cross_references_company_id", "cross_references", ["company_id"])
    op.create_index("ix_cross_references_source_article", "cross_references", ["source_article"])
    op.create_index("ix_cross_references_target_article", "cross_references", ["target_article"])

    op.create_table(
        "part_returns",
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
            "part_request_id",
            sa.Uuid(),
            sa.ForeignKey("part_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "quote_id",
            sa.Uuid(),
            sa.ForeignKey("quotes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "vehicle_id",
            sa.Uuid(),
            sa.ForeignKey("vehicles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("article", sa.String(120), nullable=False),
        sa.Column("brand", sa.String(80), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(40), nullable=False, server_default="returned"),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_part_returns_company_id", "part_returns", ["company_id"])
    op.create_index("ix_part_returns_part_request_id", "part_returns", ["part_request_id"])
    op.create_index("ix_part_returns_order_id", "part_returns", ["order_id"])
    op.create_index("ix_part_returns_quote_id", "part_returns", ["quote_id"])
    op.create_index("ix_part_returns_vehicle_id", "part_returns", ["vehicle_id"])

    op.create_table(
        "part_fitment_evidence",
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
            "part_request_id",
            sa.Uuid(),
            sa.ForeignKey("part_requests.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "vehicle_id",
            sa.Uuid(),
            sa.ForeignKey("vehicles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("article", sa.String(120), nullable=False),
        sa.Column("brand", sa.String(80), nullable=False, server_default=""),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0.0000"),
        sa.Column("detail", sa.JSON(), nullable=False),
    )
    op.create_index("ix_part_fitment_evidence_company_id", "part_fitment_evidence", ["company_id"])
    op.create_index(
        "ix_part_fitment_evidence_part_request_id", "part_fitment_evidence", ["part_request_id"]
    )
    op.create_index("ix_part_fitment_evidence_vehicle_id", "part_fitment_evidence", ["vehicle_id"])
    op.create_index("ix_part_fitment_evidence_article", "part_fitment_evidence", ["article"])


def downgrade() -> None:
    op.drop_table("part_fitment_evidence")
    op.drop_table("part_returns")
    op.drop_table("cross_references")
    op.drop_table("catalog_fitments")

"""company policy engine: company_policies table

Revision ID: a1b2c3d4e5fa
Revises: a1b2c3d4e5f9
Create Date: 2026-08-07 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5fa"
down_revision: Union[str, None] = "a1b2c3d4e5f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("company_policies"):
        op.create_table(
            "company_policies",
            sa.Column("id", UUID, primary_key=True),
            sa.Column(
                "company_id",
                UUID,
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("pricing_policy", postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column("supplier_policy", postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column("approval_policy", postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column("sales_policy", postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column("security_policy", postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("company_id", name="uq_company_policies_company_id"),
        )
        op.create_index(
            "ix_company_policies_company_id", "company_policies", ["company_id"]
        )


def downgrade() -> None:
    op.drop_index("ix_company_policies_company_id", table_name="company_policies")
    op.drop_table("company_policies")

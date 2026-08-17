"""sprint 4.3: smart offer ranking — composite score per offer

The pricing engine no longer picks "best" by price alone. Each priced offer
gets a composite ``rank`` (1 = best), a normalized ``rank_score`` in [0, 1]
and a list of human-readable ``rank_reasons`` (JSON) explaining why the offer
ranked where it did. Signals: price, delivery days, supplier reliability
(computed in sprint 4.2), fitment confidence (direct vs cross) and quantity.

Revision ID: b2c3d4e5f611
Revises: a1b2c3d4e610
Create Date: 2026-08-13 15:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f611"
down_revision: str | None = "a1b2c3d4e610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("supplier_offers", sa.Column("rank", sa.Integer(), nullable=True))
    op.add_column(
        "supplier_offers", sa.Column("rank_score", sa.Numeric(5, 4), nullable=True)
    )
    op.add_column(
        "supplier_offers", sa.Column("rank_reasons", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("supplier_offers", "rank_reasons")
    op.drop_column("supplier_offers", "rank_score")
    op.drop_column("supplier_offers", "rank")

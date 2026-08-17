"""sprint 4.4: customer garage / memory

The customer gets a persistent "garage" (the list of their cars) and a memory
blob on the Customer row: segment preference (economy/middle/premium), average
check (computed from orders) and free-form preferences. The intake flow then
reuses the garage so "need an air filter" no longer needs the customer to type
the car — the agent already knows it.

Revision ID: c3d4e5f612
Revises: b2c3d4e5f611
Create Date: 2026-08-13 16:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f612"
down_revision: str | None = "b2c3d4e5f611"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("memory", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("customers", "memory")

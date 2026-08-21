"""add pack routes (gateway namespaces)

Revision ID: 9c1e5f6a7b8c
Revises: 5b8a2c4d1e0f
Create Date: 2026-08-19 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '9c1e5f6a7b8c'
down_revision: str | None = '5b8a2c4d1e0f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('packs', sa.Column('routes', sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade() -> None:
    op.drop_column('packs', 'routes')

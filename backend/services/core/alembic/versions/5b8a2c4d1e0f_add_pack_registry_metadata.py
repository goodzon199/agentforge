"""add pack registry metadata

Revision ID: 5b8a2c4d1e0f
Revises: 4dd25de42969
Create Date: 2026-08-19 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '5b8a2c4d1e0f'
down_revision: str | None = '4dd25de42969'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('packs', sa.Column('developer', sa.String(length=120), nullable=False, server_default=''))
    op.add_column('packs', sa.Column('homepage', sa.String(length=255), nullable=False, server_default=''))
    op.add_column('packs', sa.Column('license', sa.String(length=64), nullable=False, server_default=''))
    op.add_column('packs', sa.Column('dependencies', sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column('packs', sa.Column('checksum', sa.String(length=64), nullable=False, server_default=''))
    op.add_column('packs', sa.Column('signature', sa.Text(), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('packs', 'signature')
    op.drop_column('packs', 'checksum')
    op.drop_column('packs', 'dependencies')
    op.drop_column('packs', 'license')
    op.drop_column('packs', 'homepage')
    op.drop_column('packs', 'developer')

"""add packs table

Revision ID: de265f8123bd
Revises: f3f7d6c38e9c
Create Date: 2026-08-17 12:15:05.558304

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'de265f8123bd'
down_revision: str | None = 'f3f7d6c38e9c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('packs',
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('version', sa.String(length=32), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('base_url', sa.String(length=255), nullable=False),
    sa.Column('required_core_version', sa.String(length=32), nullable=False),
    sa.Column('manifest', sa.JSON(), nullable=True),
    sa.Column('agents', sa.JSON(), nullable=False),
    sa.Column('permissions', sa.JSON(), nullable=False),
    sa.Column('workflows', sa.JSON(), nullable=False),
    sa.Column('tools', sa.JSON(), nullable=False),
    sa.Column('state', sa.Enum('installed', 'configured', 'active', 'degraded', 'disabled', 'upgrade_required', name='pack_state'), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('last_healthcheck_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_health_ok', sa.Boolean(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_packs_name'), 'packs', ['name'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_packs_name'), table_name='packs')
    op.drop_table('packs')

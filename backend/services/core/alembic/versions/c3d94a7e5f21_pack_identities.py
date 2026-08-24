"""pack identities (sprint 5.9.1)

Revision ID: c3d94a7e5f21
Revises: 9c1e5f6a7b8c
Create Date: 2026-08-24 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'c3d94a7e5f21'
down_revision: str | None = '9c1e5f6a7b8c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'pack_identities',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('pack_id', sa.String(length=80), nullable=False),
        sa.Column('service_id', sa.String(length=120), nullable=False, server_default=''),
        sa.Column(
            'status',
            sa.Enum('active', 'disabled', 'revoked', name='pack_identity_status'),
            nullable=False,
            server_default='active',
        ),
        sa.Column('bootstrap_secret_hash', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('dispatch_secret_hash', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('credential_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_authenticated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pack_identities_pack_id', 'pack_identities', ['pack_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_pack_identities_pack_id', table_name='pack_identities')
    op.drop_table('pack_identities')
    sa.Enum(name='pack_identity_status').drop(op.get_bind(), checkfirst=True)

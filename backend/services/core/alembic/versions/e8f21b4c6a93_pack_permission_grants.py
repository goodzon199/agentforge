"""pack permission grants and declared projection (sprint 5.9.2)

Revision ID: e8f21b4c6a93
Revises: c3d94a7e5f21
Create Date: 2026-08-24 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'e8f21b4c6a93'
down_revision: str | None = 'c3d94a7e5f21'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'pack_permission_grants',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('pack_id', sa.String(length=80), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('permission', sa.String(length=80), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='active'),
        sa.Column('grant_source', sa.String(length=32), nullable=False, server_default='admin'),
        sa.Column('granted_by_user_id', sa.UUID(), nullable=True),
        sa.Column('granted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_by_user_id', sa.UUID(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_pack_grants_pack_perm', 'pack_permission_grants', ['pack_id', 'permission']
    )
    op.create_table(
        'pack_declared_permissions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('pack_id', sa.String(length=80), nullable=False),
        sa.Column('permission', sa.String(length=80), nullable=False),
        sa.Column('manifest_version', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('declared_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_pack_declared_pack_perm', 'pack_declared_permissions', ['pack_id', 'permission']
    )

    # Migration bootstrap (one-time, docs/PACK_SECURITY.md 5.9.2): existing
    # trusted builtin packs keep working — declared -> granted globally.
    # Every OTHER pack starts with empty grants and awaits admin review.
    op.execute("""
        INSERT INTO pack_declared_permissions
            (id, pack_id, permission, manifest_version, declared_at)
        SELECT gen_random_uuid(), p.name, perm::text, p.version, now()
        FROM packs p, jsonb_array_elements_text(p.permissions::jsonb) AS perm
    """)
    op.execute("""
        INSERT INTO pack_permission_grants
            (id, pack_id, tenant_id, permission, status, grant_source,
             granted_by_user_id, granted_at)
        SELECT gen_random_uuid(), p.name, NULL, perm::text,
               'active', 'migration_bootstrap', NULL, now()
        FROM packs p, jsonb_array_elements_text(p.permissions::jsonb) AS perm
        WHERE p.name IN ('autoparts', 'beauty')
    """)


def downgrade() -> None:
    op.drop_index('ix_pack_declared_pack_perm', table_name='pack_declared_permissions')
    op.drop_table('pack_declared_permissions')
    op.drop_index('ix_pack_grants_pack_perm', table_name='pack_permission_grants')
    op.drop_table('pack_permission_grants')

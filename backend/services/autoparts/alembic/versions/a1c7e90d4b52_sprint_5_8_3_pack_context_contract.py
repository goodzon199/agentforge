"""sprint 5.8.3 pack context contract

domain_thread_links (core conversation -> local domain thread anchors) and
core_* provenance references on part_requests.

Revision ID: a1c7e90d4b52
Revises: 27f635876c13
Create Date: 2026-08-21 10:05:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a1c7e90d4b52'
down_revision: str | None = '27f635876c13'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('domain_thread_links',
    sa.Column('conversation_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('core_customer_id', sa.UUID(), nullable=True),
    sa.Column('core_company_id', sa.UUID(), nullable=True),
    sa.Column('channel', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('core_conversation_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('core_conversation_id')
    )
    op.create_index(op.f('ix_domain_thread_links_conversation_id'), 'domain_thread_links', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_domain_thread_links_core_company_id'), 'domain_thread_links', ['core_company_id'], unique=False)
    op.create_index(op.f('ix_domain_thread_links_core_customer_id'), 'domain_thread_links', ['core_customer_id'], unique=False)
    op.create_index(op.f('ix_domain_thread_links_customer_id'), 'domain_thread_links', ['customer_id'], unique=False)
    op.add_column('part_requests', sa.Column('core_conversation_id', sa.UUID(), nullable=True))
    op.add_column('part_requests', sa.Column('core_message_id', sa.UUID(), nullable=True))
    op.add_column('part_requests', sa.Column('core_customer_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_part_requests_core_conversation_id'), 'part_requests', ['core_conversation_id'], unique=False)
    op.create_index(op.f('ix_part_requests_core_customer_id'), 'part_requests', ['core_customer_id'], unique=False)
    op.create_index(op.f('ix_part_requests_core_message_id'), 'part_requests', ['core_message_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_part_requests_core_message_id'), table_name='part_requests')
    op.drop_index(op.f('ix_part_requests_core_customer_id'), table_name='part_requests')
    op.drop_index(op.f('ix_part_requests_core_conversation_id'), table_name='part_requests')
    op.drop_column('part_requests', 'core_customer_id')
    op.drop_column('part_requests', 'core_message_id')
    op.drop_column('part_requests', 'core_conversation_id')
    op.drop_index(op.f('ix_domain_thread_links_customer_id'), table_name='domain_thread_links')
    op.drop_index(op.f('ix_domain_thread_links_core_customer_id'), table_name='domain_thread_links')
    op.drop_index(op.f('ix_domain_thread_links_core_company_id'), table_name='domain_thread_links')
    op.drop_index(op.f('ix_domain_thread_links_conversation_id'), table_name='domain_thread_links')
    op.drop_table('domain_thread_links')

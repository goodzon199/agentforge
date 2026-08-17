"""security (sprint 3.7): audit_events journal

Revision ID: a1b2c3d4e600
Revises: a1b2c3d4e5ff
Create Date: 2026-08-11 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "a1b2c3d4e600"
down_revision: Union[str, None] = "a1b2c3d4e5ff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "audit_events" not in inspector.get_table_names():
        op.create_table(
            "audit_events",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "company_id",
                UUID(as_uuid=True),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("actor_type", sa.String(20), nullable=False),
            sa.Column("action", sa.String(80), nullable=False),
            sa.Column("entity_type", sa.String(60), nullable=False),
            sa.Column("entity_id", sa.String(36), nullable=True),
            sa.Column("ip_address", sa.String(64), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_audit_events_company_id", "audit_events", ["company_id"])
        op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
        op.create_index("ix_audit_events_action", "audit_events", ["action"])
        op.create_index("ix_audit_events_entity_id", "audit_events", ["entity_id"])
        op.create_index(
            "ix_audit_events_company_created",
            "audit_events",
            ["company_id", "created_at"],
        )
        op.create_index(
            "ix_audit_events_action_created",
            "audit_events",
            ["action", "created_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_audit_events_action_created", table_name="audit_events")
    op.drop_index("ix_audit_events_company_created", table_name="audit_events")
    op.drop_index("ix_audit_events_entity_id", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_user_id", table_name="audit_events")
    op.drop_index("ix_audit_events_company_id", table_name="audit_events")
    op.drop_table("audit_events")

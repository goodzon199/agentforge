"""pack dispatches: active-dispatch binding for workload tokens (5.9.3)"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "b4d08a1f7e62"
down_revision = "e8f21b4c6a93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pack_dispatches",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "dispatch_id", sa.String(length=64), nullable=False, index=True, unique=True
        ),
        sa.Column("pack_id", sa.String(length=80), nullable=False),
        sa.Column("task_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("company_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("operation", sa.String(length=160), nullable=False),
        sa.Column("workload_jti", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "completed",
                "failed",
                "superseded",
                name="pack_dispatch_status",
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("replayed_from", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_pack_dispatches_task_status", "pack_dispatches", ["task_id", "status"]
    )
    op.create_index(
        "ix_pack_dispatches_pack_status", "pack_dispatches", ["pack_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_pack_dispatches_pack_status", table_name="pack_dispatches")
    op.drop_index("ix_pack_dispatches_task_status", table_name="pack_dispatches")
    op.drop_table("pack_dispatches")
    sa.Enum(name="pack_dispatch_status").drop(op.get_bind(), checkfirst=True)

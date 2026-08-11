"""security (sprint 3.7): audit_events.created_at server default

The audit_events table may have been auto-created (create_all fast path)
while the model still declared created_at without a server default, leaving
``created_at`` WITHOUT a default. Backfill the default so INSERTs never
violate the not-null constraint.

Revision ID: a1b2c3d4e601
Revises: a1b2c3d4e600
Create Date: 2026-08-11 13:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e601"
down_revision: Union[str, None] = "a1b2c3d4e600"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "audit_events" in inspector.get_table_names():
        columns = {c["name"]: c for c in inspector.get_columns("audit_events")}
        created = columns.get("created_at")
        if created is not None and created.get("server_default") is None:
            op.alter_column(
                "audit_events",
                "created_at",
                server_default=sa.func.now(),
            )


def downgrade() -> None:
    op.alter_column("audit_events", "created_at", server_default=None)

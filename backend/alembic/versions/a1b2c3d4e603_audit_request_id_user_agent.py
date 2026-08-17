"""security (sprint 3.7.1): audit_events request_id / user_agent columns

The audit journal already stores ip_address (always null so far). Add
``request_id`` (X-Request-ID correlation) and ``user_agent`` so records
captured by the audit-context middleware are linkable to access logs and
carry the client's browser/agent.

Revision ID: a1b2c3d4e603
Revises: a1b2c3d4e602
Create Date: 2026-08-11 15:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e603"
down_revision: Union[str, None] = "a1b2c3d4e602"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column("request_id", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "audit_events",
        sa.Column("user_agent", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_audit_events_request_id"), "audit_events", ["request_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_events_request_id"), table_name="audit_events")
    op.drop_column("audit_events", "user_agent")
    op.drop_column("audit_events", "request_id")

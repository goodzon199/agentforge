"""sprint 3.8.3a: auto-send safety — quote.version + auto-send audit trail

Controlled Auto hardening: the quote carries an optimistic-lock version (so a
stale worker can never auto-send an outdated snapshot) and the full decision
snapshot (auto_send_decision / auto_sent / auto_sent_at) so we can audit why a
quote went out without a human.

Revision ID: a1b2c3d4e606
Revises: a1b2c3d4e605
Create Date: 2026-08-13 10:30:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e606"
down_revision: str | None = "a1b2c3d4e605"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "quotes",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "quotes",
        sa.Column("auto_send_decision", sa.JSON(), nullable=True),
    )
    op.add_column(
        "quotes",
        sa.Column("auto_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "quotes",
        sa.Column("auto_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Two workers must never both auto-send the same quote version: the send
    # action's idempotency key is now UNIQUE, so the second insert aborts.
    op.create_unique_constraint(
        "uq_agent_actions_idempotency_key", "agent_actions", ["idempotency_key"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_agent_actions_idempotency_key", "agent_actions", type_="unique"
    )
    op.drop_column("quotes", "auto_sent_at")
    op.drop_column("quotes", "auto_sent")
    op.drop_column("quotes", "auto_send_decision")
    op.drop_column("quotes", "version")

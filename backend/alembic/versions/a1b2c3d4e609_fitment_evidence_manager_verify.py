"""sprint 4.1: fitment explainability — manager verify evidence

The Manager Verify buttons ([✓]/[✕]) create a PartFitmentEvidence row that
must record WHO verified and WHAT the verdict was, so the explainability UI
can show "confirmed by manager" and the engine can learn from rejections.

Revision ID: a1b2c3d4e609
Revises: a1b2c3d4e608
Create Date: 2026-08-13 13:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e609"
down_revision: str | None = "a1b2c3d4e608"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "part_fitment_evidence",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
    )
    # result: confirmed / rejected — the manager's verdict on this pick.
    op.add_column(
        "part_fitment_evidence",
        sa.Column("result", sa.String(24), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("part_fitment_evidence", "result")
    op.drop_column("part_fitment_evidence", "user_id")

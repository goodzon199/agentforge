"""add missing traces root_span fk

Revision ID: 7e95954f104a
Revises: de265f8123bd
Create Date: 2026-08-17 12:16:22.409690

"""
from collections.abc import Sequence

from alembic import op

revision: str = '7e95954f104a'
down_revision: str | None = 'de265f8123bd'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Pre-existing drift: the initial migration declared root_span_id FK with
    # use_alter=True inside create_table, but the constraint was never emitted
    # as ALTER TABLE. Add it now so the model and DB schema agree.
    op.create_foreign_key(
        "fk_traces_root_span_id",
        "traces",
        "trace_spans",
        ["root_span_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_traces_root_span_id", "traces", type_="foreignkey")

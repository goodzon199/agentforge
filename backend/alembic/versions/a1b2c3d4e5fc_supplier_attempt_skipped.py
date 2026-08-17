"""supplier attempt status: add 'skipped'

Revision ID: a1b2c3d4e5fc
Revises: a1b2c3d4e5fb
Create Date: 2026-08-08 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5fc"
down_revision: Union[str, None] = "a1b2c3d4e5fb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("ALTER TYPE supplier_attempt_status ADD VALUE IF NOT EXISTS 'skipped'")


def downgrade() -> None:
    # Recreate the enum without 'skipped' (any skipped rows become failed).
    op.execute("UPDATE supplier_search_attempts SET status = 'failed' WHERE status = 'skipped'")
    op.execute("ALTER TABLE supplier_search_attempts ALTER COLUMN status TYPE varchar USING status::varchar")
    op.execute("DROP TYPE supplier_attempt_status")
    op.execute("CREATE TYPE supplier_attempt_status AS ENUM ('pending','succeeded','failed')")
    op.execute("ALTER TABLE supplier_search_attempts ALTER COLUMN status TYPE supplier_attempt_status USING status::supplier_attempt_status")

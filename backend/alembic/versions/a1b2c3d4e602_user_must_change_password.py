"""security (sprint 3.7.1): users.must_change_password

Bootstrap / temporary accounts (seeded admin in production, manager accounts
created by an owner) must set a real password at first login. Adds a boolean
column to ``users``; while it is True the API rejects everything except
``/auth/change-password`` and ``/auth/me``.

Revision ID: a1b2c3d4e602
Revises: a1b2c3d4e601
Create Date: 2026-08-11 14:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e602"
down_revision: Union[str, None] = "a1b2c3d4e601"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")

"""security (sprint 3.7.1): users.role

Add a tenant access level to users for the user-management API:
``owner | admin | manager | viewer`` (default ``manager``). The seeded
bootstrap admin is the ``owner``.

Revision ID: a1b2c3d4e604
Revises: a1b2c3d4e603
Create Date: 2026-08-11 16:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e604"
down_revision: Union[str, None] = "a1b2c3d4e603"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="manager",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "role")

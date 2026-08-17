"""sprint 4.0: hardening — normalize legacy 10-point supplier ratings to 0..1

Sprint 3.8.3a already *blocks* out-of-range ratings at decision time, but any
legacy ``settings.rating`` that predates the 0..1 convention (e.g. 9.5 out of
10) must also be *fixed in the database* so the analytics and the manager
dashboard never display a value outside the documented scale.

Revision ID: a1b2c3d4e608
Revises: a1b2c3d4e607
Create Date: 2026-08-13 11:30:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e608"
down_revision: str | None = "a1b2c3d4e607"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _normalize(value) -> float:
    if value is None:
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number < 0.0:
        return 0.0
    if number > 1.0:
        # Legacy 10-point scale: 9.5 (out of 10) == 0.95.
        if number <= 10.0:
            return round(number / 10.0, 4)
        return 1.0
    return round(number, 4)


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, settings FROM suppliers")).mappings().all()
    for row in rows:
        settings = dict(row["settings"] or {})
        if settings.get("rating") is None:
            continue
        normalized = _normalize(settings["rating"])
        if normalized == float(settings["rating"]):
            continue
        settings["rating"] = normalized
        connection.execute(
            sa.text("UPDATE suppliers SET settings = :settings WHERE id = :id"),
            {"settings": settings, "id": row["id"]},
        )


def downgrade() -> None:
    # No-op: a normalization is not reversible (the original scale is gone).
    pass

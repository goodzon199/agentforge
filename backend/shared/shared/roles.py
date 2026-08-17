from __future__ import annotations

"""Role and status constants shared between core and autoparts services."""

# Roles in descending privilege: owner > admin > manager > viewer.
WRITE_ROLES = frozenset({"owner", "admin", "manager"})
VIEWER_ROLE = "viewer"


def is_writer_role(role: str | None) -> bool:
    """True for owner/admin/manager (and unscoped/system users)."""
    if role is None:
        return True
    return role in WRITE_ROLES
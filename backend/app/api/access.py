from __future__ import annotations

import uuid

from fastapi import HTTPException, status


def company_allowed(user, company_id) -> bool:
    """A user may only act on resources of their own company. A user without
    a company scope (unscoped/system) is treated as global."""
    if user is None or user.company_id is None:
        return True
    return str(user.company_id) == str(company_id)


def ensure_company(user, company_id) -> None:
    if not company_allowed(user, company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ к данным другой компании запрещён.",
        )


def company_scope(user) -> uuid.UUID | None:
    """Tenant filter for list queries: None means no restriction (global view)."""
    if user is None:
        return None
    return user.company_id

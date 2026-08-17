from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass

# Request-scoped metadata the audit service can attach to records without any
# FastAPI coupling. Populated by ``AuditContextMiddleware`` (request_id, IP,
# user-agent) and enriched with the authenticated user by ``get_current_user``.
_current_audit: contextvars.ContextVar[AuditContext | None] = contextvars.ContextVar(
    "agentos_audit_context", default=None
)


@dataclass
class AuditContext:
    """Who/where/what-request an audited action happened in.

    ``user_id`` / ``company_id`` are best-effort enrichments: callers that
    already pass these explicitly to ``AuditService.record`` always win.
    """

    request_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    user_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None


def get_audit_context() -> AuditContext | None:
    return _current_audit.get()


def set_audit_context(ctx: AuditContext) -> contextvars.Token:
    return _current_audit.set(ctx)


def reset_audit_context(token: contextvars.Token) -> None:
    _current_audit.reset(token)


def enrich_audit_user(user_id: uuid.UUID, company_id: uuid.UUID | None) -> None:
    """Attach the authenticated user to the current request's audit context."""
    ctx = _current_audit.get()
    if ctx is None:
        ctx = AuditContext()
        _current_audit.set(ctx)
    ctx.user_id = user_id
    ctx.company_id = company_id

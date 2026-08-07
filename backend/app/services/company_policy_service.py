from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.policies import DEFAULT_POLICIES, DEFAULT_SECURITY_POLICY, merge_policy
from app.models import Company, CompanyPolicy

_DOMAINS = ("pricing", "supplier", "approval", "sales", "security")


class CompanyPolicyService:
    """Read/write a company's business rules, merged over built-in defaults."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Read ------------------------------------------------------------

    def get(self, company_id: uuid.UUID) -> CompanyPolicy:
        """The company's policy row (created empty on first access)."""
        stmt = select(CompanyPolicy).where(CompanyPolicy.company_id == company_id)
        policy = self.db.scalars(stmt).first()
        if policy is None:
            policy = CompanyPolicy(company_id=company_id)
            self.db.add(policy)
            self.db.flush()
        return policy

    def policy(self, company_id: uuid.UUID, domain: str) -> dict[str, Any]:
        """Effective policy for one domain: defaults merged with overrides."""
        row = self.get(company_id)
        stored = getattr(row, f"{domain}_policy")
        return merge_policy(DEFAULT_POLICIES[domain], stored)

    def effective(self, company_id: uuid.UUID) -> dict[str, dict[str, Any]]:
        return {domain: self.policy(company_id, domain) for domain in _DOMAINS}

    @staticmethod
    def defaults() -> dict[str, dict[str, Any]]:
        return DEFAULT_POLICIES

    # --- Write -----------------------------------------------------------

    def update(
        self,
        company_id: uuid.UUID,
        *,
        pricing: dict[str, Any] | None = None,
        supplier: dict[str, Any] | None = None,
        approval: dict[str, Any] | None = None,
        sales: dict[str, Any] | None = None,
        security: dict[str, Any] | None = None,
    ) -> CompanyPolicy:
        row = self.get(company_id)
        for domain, payload in (
            ("pricing", pricing),
            ("supplier", supplier),
            ("approval", approval),
            ("sales", sales),
            ("security", security),
        ):
            if payload is None:
                continue
            if not isinstance(payload, dict):
                raise ValueError(f"Политика «{domain}» должна быть объектом.")
            current = merge_policy(
                DEFAULT_POLICIES[domain], getattr(row, f"{domain}_policy")
            )
            current.update(payload)
            setattr(row, f"{domain}_policy", current)
        self._sync_security(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _sync_security(self, row: CompanyPolicy) -> None:
        """Keep the PermissionEngine overrides in ``company.settings.permissions``.

        ``security_policy`` is the business-facing view; the engine keeps
        reading ``company.settings.permissions`` as its single source.
        """
        security = merge_policy(DEFAULT_SECURITY_POLICY, row.security_policy)
        permissions = {
            key: str(value).upper() for key, value in (security.get("permissions") or {}).items()
        }
        company = self.db.get(Company, row.company_id)
        if company is None:
            return
        settings = dict(company.settings or {})
        if permissions:
            settings["permissions"] = permissions
        else:
            settings.pop("permissions", None)
        company.settings = settings

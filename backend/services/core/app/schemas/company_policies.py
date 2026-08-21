from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel


class CompanyPoliciesRead(BaseModel):
    company_id: uuid.UUID
    pricing: dict[str, Any]
    supplier: dict[str, Any]
    approval: dict[str, Any]
    sales: dict[str, Any]
    security: dict[str, Any]
    defaults: dict[str, dict[str, Any]]


class CompanyPoliciesUpdateIn(BaseModel):
    pricing: dict[str, Any] | None = None
    supplier: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    sales: dict[str, Any] | None = None
    security: dict[str, Any] | None = None

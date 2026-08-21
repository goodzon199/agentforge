from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel


class PermissionEvaluateIn(BaseModel):
    action: str
    resource: str | None = None
    agent_id: uuid.UUID | None = None
    context: dict[str, Any] = {}


class PermissionDecisionRead(BaseModel):
    allowed: bool
    requires_approval: bool
    risk_level: str
    reason: str


class PermissionPolicyRead(BaseModel):
    action: str
    resource: str | None = None
    risk_level: str
    requires_approval: bool
    source: str


class PermissionPolicyUpdateIn(BaseModel):
    permissions: dict[str, str] = {}


class PermissionPolicyUpdateRead(BaseModel):
    permissions: dict[str, str]

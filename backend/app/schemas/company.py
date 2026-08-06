from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    slug: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9-]+$")
    description: str = ""
    agent_quota: int = Field(default=10, ge=1, le=1000)


class CompanyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    agent_quota: int | None = Field(default=None, ge=1, le=1000)
    is_active: bool | None = None


class CompanyRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str
    is_active: bool
    agent_quota: int
    created_at: datetime
    updated_at: datetime
    agents_count: int = 0
    tasks_count: int = 0

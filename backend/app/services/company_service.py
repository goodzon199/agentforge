from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company


class CompanyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, *, name: str, slug: str, description: str = "", agent_quota: int = 10) -> Company:
        company = Company(name=name, slug=slug, description=description, agent_quota=agent_quota)
        self.db.add(company)
        return company

    def list(self) -> list[Company]:
        stmt = select(Company).order_by(Company.created_at.desc())
        return list(self.db.scalars(stmt).unique().all())

    def get(self, company_id: uuid.UUID) -> Company | None:
        return self.db.get(Company, company_id)

    def get_by_slug(self, slug: str) -> Company | None:
        return self.db.scalars(select(Company).where(Company.slug == slug)).first()

    def update(self, company: Company, updates: dict[str, Any]) -> Company:
        for key, value in updates.items():
            if hasattr(company, key) and key not in ("id",):
                setattr(company, key, value)
        return company

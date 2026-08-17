from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company


class HelloPackService:
    """Tiny demo service: greets a company by name.

    Intentionally minimal — HelloPack exists to show the package shape
    (service + router + test) that new domain packages should follow, not to
    add real business logic.
    """

    def __init__(self, db: Session):
        self.db = db

    def greet(self, company_id: object) -> str:
        company = self.db.scalars(
            select(Company).where(Company.id == company_id)
        ).first()
        if company is None:
            return "Hello, unknown company!"
        return f"Hello, {company.name}!"

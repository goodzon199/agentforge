from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.models import User
from app.services.audit_service import AuditService


class UserService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        return self.db.scalars(stmt).first()

    def create(
        self,
        *,
        email: str,
        password: str,
        full_name: str = "",
        is_superuser: bool = False,
        company_id=None,
    ) -> User:
        validate_password_strength(password)
        user = User(
            email=email.lower(),
            full_name=full_name,
            hashed_password=hash_password(password),
            is_superuser=is_superuser,
            is_active=True,
            company_id=company_id,
        )
        self.db.add(user)
        AuditService(self.db).record(
            action="user.create",
            entity_type="user",
            entity_id=str(user.id),
            company_id=company_id,
            actor_type="system",
            detail={"email": user.email, "is_superuser": is_superuser},
        )
        return user

    def authenticate(self, email: str, password: str) -> User | None:
        user = self.get_by_email(email)
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    def to_dict(self, user: User) -> dict[str, object]:
        return {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "is_superuser": user.is_superuser,
            "company_id": str(user.company_id) if user.company_id else None,
            "created_at": user.created_at.isoformat(),
        }

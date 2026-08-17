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

ROLES = frozenset({"owner", "admin", "manager", "viewer"})
_ROLES = ROLES


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
        must_change_password: bool = False,
        role: str = "manager",
    ) -> User:
        validate_password_strength(password)
        user = User(
            email=email.lower(),
            full_name=full_name,
            hashed_password=hash_password(password),
            is_superuser=is_superuser,
            is_active=True,
            company_id=company_id,
            must_change_password=must_change_password,
            role=role,
        )
        self.db.add(user)
        AuditService(self.db).record(
            action="user.create",
            entity_type="user",
            entity_id=str(user.id),
            company_id=company_id,
            actor_type="system",
            detail={
                "email": user.email,
                "is_superuser": is_superuser,
                "role": role,
            },
        )
        return user

    def list(
        self,
        *,
        company_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[User]:
        stmt = select(User).order_by(User.created_at.asc())
        if company_id is not None:
            stmt = stmt.where(User.company_id == company_id)
        return list(
            self.db.scalars(stmt.offset(offset).limit(limit)).unique().all()
        )

    def update(
        self,
        user: User,
        *,
        full_name: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> User:
        if full_name is not None:
            user.full_name = full_name
        if role is not None:
            if role not in _ROLES:
                raise ValueError(
                    f"Роль должна быть одной из: {', '.join(sorted(_ROLES))}."
                )
            user.role = role
        if is_active is not None:
            user.is_active = is_active
        AuditService(self.db).record(
            action="user.update",
            entity_type="user",
            entity_id=str(user.id),
            company_id=user.company_id,
            actor_type="user",
            user_id=user.id,
            detail={
                "email": user.email,
                "role": user.role,
                "is_active": user.is_active,
            },
        )
        return user

    def set_active(self, user: User, is_active: bool) -> User:
        user.is_active = is_active
        AuditService(self.db).record(
            action="user.disable" if not is_active else "user.enable",
            entity_type="user",
            entity_id=str(user.id),
            company_id=user.company_id,
            actor_type="user",
            user_id=user.id,
            detail={"email": user.email, "is_active": is_active},
        )
        return user

    def reset_password(self, user: User, new_password: str) -> User:
        """Set a temporary password; the account must change it at next login."""
        validate_password_strength(new_password)
        user.hashed_password = hash_password(new_password)
        user.must_change_password = True
        AuditService(self.db).record(
            action="user.reset_password",
            entity_type="user",
            entity_id=str(user.id),
            company_id=user.company_id,
            actor_type="user",
            user_id=user.id,
            detail={"email": user.email},
        )
        return user

    def authenticate(self, email: str, password: str) -> User | None:
        user = self.get_by_email(email)
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    def change_password(
        self, user: User, current_password: str, new_password: str
    ) -> User:
        """Verify the current password and set a new one (clears the flag)."""
        if not verify_password(current_password, user.hashed_password):
            raise ValueError("Текущий пароль неверен.")
        validate_password_strength(new_password)
        user.hashed_password = hash_password(new_password)
        user.must_change_password = False
        AuditService(self.db).record(
            action="user.change_password",
            entity_type="user",
            entity_id=str(user.id),
            company_id=user.company_id,
            actor_type="user",
            user_id=user.id,
            detail={"email": user.email},
        )
        return user

    def to_dict(self, user: User) -> dict[str, object]:
        return {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "is_superuser": user.is_superuser,
            "company_id": str(user.company_id) if user.company_id else None,
            "must_change_password": user.must_change_password,
            "role": user.role,
            "created_at": user.created_at.isoformat(),
        }

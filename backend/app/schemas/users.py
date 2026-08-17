from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.user_service import ROLES

ROLE_NAMES = sorted(ROLES)


class UserCreate(BaseModel):
    email: str = Field(min_length=3)
    full_name: str = Field(default="", max_length=180)
    role: str = Field(default="manager")
    # Temporary password (required; the account changes it at first login).
    password: str = Field(min_length=1)

    def model_post_init(self, __context) -> None:
        if self.role not in ROLES:
            raise ValueError(f"Роль должна быть одной из: {', '.join(ROLE_NAMES)}.")
        if "@" not in self.email:
            raise ValueError("Некорректный e-mail.")


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, max_length=180)
    role: str | None = None
    is_active: bool | None = None

    def model_post_init(self, __context) -> None:
        if self.role is not None and self.role not in ROLES:
            raise ValueError(f"Роль должна быть одной из: {', '.join(ROLE_NAMES)}.")


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=1)


class UserListRead(BaseModel):
    total: int
    items: list[object]

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class UserRead(ORMModel):
    id: str
    email: str
    full_name: str
    is_active: bool
    is_superuser: bool
    company_id: str | None = None
    must_change_password: bool = False
    role: str = "manager"
    created_at: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead

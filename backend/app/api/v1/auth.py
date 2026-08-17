from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import (
    check_public_business_rate,
    get_current_user,
    get_user_service,
)
from app.core.database import get_db
from app.core.rate_limit import LoginThrottle
from app.core.security import create_access_token
from app.models import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    UserRead,
)
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["auth"])

_throttle = LoginThrottle()


def _to_read(user: User) -> UserRead:
    return UserRead(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        company_id=str(user.company_id) if user.company_id else None,
        must_change_password=user.must_change_password,
        role=user.role,
        created_at=user.created_at.isoformat(),
    )


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    users: UserService = Depends(get_user_service),
    _: None = Depends(check_public_business_rate),
) -> LoginResponse:
    client_ip = request.client.host if request.client else "unknown"
    if not _throttle.request_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много попыток входа. Повторите позже.",
        )
    if _throttle.is_locked(payload.email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Аккаунт временно заблокирован из-за неудачных попыток входа.",
        )
    user = users.authenticate(payload.email, payload.password)
    if user is None:
        _throttle.record_failure(payload.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный e-mail или пароль.",
        )
    _throttle.record_success(payload.email)
    token = create_access_token(str(user.id))
    return LoginResponse(
        access_token=token,
        user=_to_read(user),
    )


@router.post("/change-password", response_model=UserRead)
def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
    db: Session = Depends(get_db),
) -> UserRead:
    try:
        users.change_password(
            user,
            payload.current_password,
            payload.new_password,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    db.commit()
    db.refresh(user)
    return _to_read(user)


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> UserRead:
    return _to_read(user)

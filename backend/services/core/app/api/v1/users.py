from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.access import company_scope
from app.api.deps import get_current_user, get_user_service
from app.core.database import get_db
from app.models import User
from app.schemas.auth import UserRead
from app.schemas.users import ResetPasswordRequest, UserCreate, UserListRead, UserPatch
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])

# Roles that may manage tenant accounts.
MANAGER_ROLES = frozenset({"owner", "admin"})


def _read(user: User) -> UserRead:
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


def _require_manager(actor: User) -> None:
    if not actor.is_superuser and actor.role not in MANAGER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Управление пользователями доступно владельцу или администратору.",
        )


def _get_managed_user(db: Session, actor: User, user_id: uuid.UUID) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
    if actor.company_id is not None and target.company_id != actor.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ к пользователю другой компании запрещён.",
        )
    return target


@router.get("", response_model=UserListRead)
def list_users(
    limit: int = 100,
    offset: int = 0,
    actor: User = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
):
    scope = company_scope(actor)
    items = users.list(company_id=scope, limit=limit, offset=offset)
    total_stmt = select(func.count()).select_from(User)
    if scope is not None:
        total_stmt = total_stmt.where(User.company_id == scope)
    total = users.db.scalar(total_stmt) or 0
    return UserListRead(total=total, items=[_read(u) for u in items])


@router.post("", response_model=UserRead, status_code=201)
def create_user(
    payload: UserCreate,
    actor: User = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
    db: Session = Depends(get_db),
):
    _require_manager(actor)
    if users.get_by_email(payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким e-mail уже существует.",
        )
    try:
        created = users.create(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            company_id=actor.company_id,
            must_change_password=True,
            role=payload.role,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    db.commit()
    db.refresh(created)
    return _read(created)


@router.patch("/{user_id}", response_model=UserRead)
def patch_user(
    user_id: uuid.UUID,
    payload: UserPatch,
    actor: User = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
    db: Session = Depends(get_db),
):
    _require_manager(actor)
    target = _get_managed_user(db, actor, user_id)
    if target.is_superuser and target.id != actor.id and not actor.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя изменять владельца платформы.",
        )
    try:
        users.update(
            target,
            full_name=payload.full_name,
            role=payload.role,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    db.commit()
    db.refresh(target)
    return _read(target)


@router.post("/{user_id}/disable", response_model=UserRead)
def disable_user(
    user_id: uuid.UUID,
    actor: User = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
    db: Session = Depends(get_db),
):
    _require_manager(actor)
    target = _get_managed_user(db, actor, user_id)
    if target.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя отключить собственный аккаунт.",
        )
    if target.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя отключить владельца платформы.",
        )
    users.set_active(target, False)
    db.commit()
    db.refresh(target)
    return _read(target)


@router.post("/{user_id}/reset-password", response_model=UserRead)
def reset_password(
    user_id: uuid.UUID,
    payload: ResetPasswordRequest,
    actor: User = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
    db: Session = Depends(get_db),
):
    _require_manager(actor)
    target = _get_managed_user(db, actor, user_id)
    try:
        users.reset_password(target, payload.new_password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    db.commit()
    db.refresh(target)
    return _read(target)

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.business_rate_limit import BusinessRateLimiter, get_business_rate_limiter
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User
from app.services.conversation_service import ConversationService
from app.services.order_service import OrderService
from app.services.part_request_service import PartRequestService
from app.services.parts_search_service import PartsSearchService
from app.services.pricing_service import PricingService
from app.services.quote_service import QuoteService
from app.services.sales_service import SalesService
from app.services.supplier_order_service import SupplierOrderService
from app.services.supplier_reliability_service import SupplierReliabilityService
from app.services.supplier_service import SupplierService
from app.services.task_service import TaskService
from app.services.user_service import UserService

_bearer = HTTPBearer(auto_error=False)

# Endpoints a user with must_change_password=True may still reach until they
# set a real password. Everything else returns 403 "password change required".
_PASSWORD_CHANGE_ALLOWED_PATHS = frozenset(
    {"/api/v1/auth/change-password", "/api/v1/auth/me"}
)


def get_task_service(db: Session = Depends(get_db)) -> TaskService:
    return TaskService(db)


def get_conversation_service(db: Session = Depends(get_db)) -> ConversationService:
    return ConversationService(db)


def get_part_request_service(db: Session = Depends(get_db)) -> PartRequestService:
    return PartRequestService(db)


def get_parts_search_service(db: Session = Depends(get_db)) -> PartsSearchService:
    return PartsSearchService(db)


def get_pricing_service(db: Session = Depends(get_db)) -> PricingService:
    return PricingService(db)


def get_quote_service(db: Session = Depends(get_db)) -> QuoteService:
    return QuoteService(db)


def get_sales_service(db: Session = Depends(get_db)) -> SalesService:
    return SalesService(db)


def get_order_service(db: Session = Depends(get_db)) -> OrderService:
    return OrderService(db)


def get_supplier_service(db: Session = Depends(get_db)) -> SupplierService:
    return SupplierService(db)


def get_supplier_order_service(db: Session = Depends(get_db)) -> SupplierOrderService:
    return SupplierOrderService(db)


def get_supplier_reliability_service(
    db: Session = Depends(get_db),
) -> SupplierReliabilityService:
    return SupplierReliabilityService(db)


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(db)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    request: Request = None,  # type: ignore[assignment]
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен недействителен или истёк.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = UserService(db).get(user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Attach the authenticated user to the request's audit context so audit
    # records carry the actor even when a service forgets to pass it.
    from app.services.audit_context import enrich_audit_user

    enrich_audit_user(user.id, user.company_id)
    if (
        user.must_change_password
        and request is not None
        and request.url.path not in _PASSWORD_CHANGE_ALLOWED_PATHS
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Требуется смена пароля при первом входе.",
        )
    return user


def check_business_rate(
    request: Request,
    user: User = Depends(get_current_user),
    limiter: BusinessRateLimiter = Depends(get_business_rate_limiter),
) -> None:
    """Per-user quota for the authenticated API (sprint 3.7.1).

    Category is derived from method + path; the key is company_id:user_id so a
    burst from one tenant never affects another. Exceeding the budget returns
    429 with a Retry-After header.
    """
    from app.core.business_rate_limit import category_for

    category = category_for(request.method, request.url.path)
    allowed, retry_after = limiter.check(
        category=category,
        company_id=user.company_id,
        user_id=user.id,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много запросов. Попробуйте позже.",
            headers={"Retry-After": str(retry_after)},
        )


def check_public_business_rate(
    request: Request,
    limiter: BusinessRateLimiter = Depends(get_business_rate_limiter),
) -> None:
    """Per-IP quota for unauthenticated endpoints (login, public web-chat)."""
    ip = request.client.host if request.client else "unknown"
    allowed, retry_after = limiter.check_public(category="public", ip=ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много запросов. Попробуйте позже.",
            headers={"Retry-After": str(retry_after)},
        )

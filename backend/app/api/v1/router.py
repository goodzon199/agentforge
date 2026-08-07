from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.v1 import (
    actions,
    agents,
    approvals,
    auth,
    companies,
    conversations,
    dashboard,
    logs,
    part_requests,
    quotes,
    settings,
    suppliers,
    tasks,
)

api_router = APIRouter()
api_router.include_router(auth.router)

# Resource routers require a valid JWT.
for module in (
    dashboard,
    companies,
    agents,
    tasks,
    logs,
    settings,
    part_requests,
    suppliers,
    approvals,
    actions,
    quotes,
):
    api_router.include_router(
        module.router,
        dependencies=[Depends(get_current_user)],
    )

api_router.include_router(
    conversations.customers_router,
    dependencies=[Depends(get_current_user)],
)
api_router.include_router(
    conversations.conversations_router,
    dependencies=[Depends(get_current_user)],
)

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.v1 import (
    actions,
    agents,
    analytics,
    approvals,
    auth,
    chat,
    companies,
    company_policies,
    conversations,
    dashboard,
    logs,
    orders,
    part_requests,
    permissions,
    quality,
    quotes,
    settings,
    suppliers,
    tasks,
)

api_router = APIRouter()
api_router.include_router(auth.router)

# Public web-chat widget channel: no JWT, identified by company public_token.
api_router.include_router(chat.router)

# Resource routers require a valid JWT.
# quality defines /agents/quality before agents defines /agents/{agent_id},
# otherwise the dynamic route swallows the exact path.
for module in (
    quality,
    dashboard,
    analytics,
    companies,
    company_policies,
    agents,
    tasks,
    logs,
    settings,
    part_requests,
    suppliers,
    permissions,
    approvals,
    actions,
    quotes,
    orders,
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

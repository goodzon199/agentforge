from fastapi import APIRouter, Depends

from app.api.deps import check_business_rate, get_current_user
from app.api.v1 import (
    agents,
    analytics,
    audit,
    auth,
    chat,
    companies,
    company_policies,
    conversations,
    dashboard,
    logs,
    ops,
    packs,
    permissions,
    quality,
    settings,
    tasks,
    traces,
    users,
    workflows,
)

api_router = APIRouter()
api_router.include_router(auth.router)

# Public web-chat widget channel: no JWT, identified by company public_token.
api_router.include_router(chat.router)

# Resource routers require a valid JWT. check_business_rate applies the
# per-user quotas (read/write/expensive/ai) derived from method + path.
# quality defines /agents/quality before agents defines /agents/{agent_id},
# otherwise the dynamic route swallows the exact path.
for module in (
    quality,
    dashboard,
    analytics,
    audit,
    companies,
    company_policies,
    agents,
    tasks,
    logs,
    settings,
    permissions,
    traces,
    users,
    ops,
    packs,
    workflows,
):
    api_router.include_router(
        module.router,
        dependencies=[Depends(get_current_user), Depends(check_business_rate)],
    )

api_router.include_router(
    conversations.customers_router,
    dependencies=[Depends(get_current_user), Depends(check_business_rate)],
)
api_router.include_router(
    conversations.conversations_router,
    dependencies=[Depends(get_current_user), Depends(check_business_rate)],
)

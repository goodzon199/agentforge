from fastapi import APIRouter, Depends

from app.api.deps import check_business_rate, get_current_user
from app.api.v1 import (
    actions,
    approvals,
    company_policies,
    conversations,
    fitment,
    garage,
    hellopack,
    manager,
    orders,
    part_requests,
    quotes,
    supplier_orders,
    suppliers,
    tasks,
)

api_router = APIRouter()

# Resource routers require a valid JWT. check_business_rate applies the
# per-user quotas (read/write/expensive/ai) derived from method + path.
for module in (
    company_policies,
    tasks,
    part_requests,
    suppliers,
    approvals,
    actions,
    quotes,
    orders,
    supplier_orders,
    manager,
    fitment,
    garage,
    hellopack,
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

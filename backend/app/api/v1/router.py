from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.v1 import agents, auth, companies, dashboard, logs, settings, tasks

api_router = APIRouter()
api_router.include_router(auth.router)

# Resource routers require a valid JWT.
for module in (dashboard, companies, agents, tasks, logs, settings):
    api_router.include_router(
        module.router,
        dependencies=[Depends(get_current_user)],
    )

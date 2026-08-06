from fastapi import APIRouter

from app.api.v1 import agents, companies, dashboard, logs, settings, tasks

api_router = APIRouter()
api_router.include_router(dashboard.router)
api_router.include_router(companies.router)
api_router.include_router(agents.router)
api_router.include_router(tasks.router)
api_router.include_router(logs.router)
api_router.include_router(settings.router)

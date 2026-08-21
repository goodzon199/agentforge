"""FastAPI application for the Beauty pack (sprint 5.5)."""

from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.api.internal import router as internal_router

logger = logging.getLogger("beauty")


class Settings(BaseSettings):
    """Minimal pack settings — no DB, no Redis, no auth."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "BeautySalon"
    environment: str = "development"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(
    title="AgentForge Beauty Salon API",
    description="Салон красоты (записи, календарь, напоминания) — Pack SDK, без core-зависимостей.",
    version="1.0.0",
    docs_url="/docs" if settings.environment != "production" else None,
)

app.include_router(internal_router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {"name": settings.app_name, "version": "1.0.0", "docs": "/docs"}

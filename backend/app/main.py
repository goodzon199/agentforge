from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine

logger = logging.getLogger("agentforge")
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def _init_database() -> None:
    """Bootstrap tables and seed demo data (dev convenience).

    Production deployments use Alembic migrations; create_all here is a
    fast path for the first run and for tests.
    """
    try:
        Base.metadata.create_all(bind=engine)
        from app.core.seeding import seed_demo

        with SessionLocal() as db:
            created = seed_demo(db)
            logger.info(
                "База готова. Компания=%s, SystemAgent=%s, EmailAgent=%s, "
                "SearchAgent=%s, знания=%s, админ=%s",
                created["company"],
                created["system_agent"],
                created["email_agent"],
                created["search_agent"],
                created["knowledge"],
                created["admin"],
            )
    except Exception:
        logger.exception(
            "База данных недоступна. API поднимется, но запросы к БД будут ошибаться."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_database()

    from app.orchestrator.worker import worker

    worker.start()
    logger.info("AgentForge API запущен в окружении %s", settings.environment)
    yield
    worker.stop()


app = FastAPI(
    title="AgentForge API",
    description="Операционная система для цифровых сотрудников.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {"name": settings.app_name, "version": "0.1.0", "docs": "/docs"}

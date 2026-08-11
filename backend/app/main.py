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


def _alembic_head_and_current() -> tuple[str | None, str | None]:
    """Return (head_revision, current_revision) without applying migrations.

    Safe to call on a fresh/empty database (current = None) and when the
    database is unreachable (raises; caller decides how to fail).
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect, text

    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()

    with engine.connect() as conn:
        if not inspect(conn).has_table("alembic_version"):
            return head, None
        version = conn.execute(text("select version_num from alembic_version")).scalar()
    return head, version


def _init_database() -> None:
    """Bootstrap schema + demo seed.

    - Development (db_auto_create=True): fast path — create_all + seed. Still
      checks the Alembic revision afterwards and warns if it drifts.
    - Production (db_auto_create=False): Alembic only. Fails fast (Raises
      RuntimeError) if the database is missing or behind `head` — the schema
      is never mutated implicitly.
    """
    try:
        if settings.db_auto_create:
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
            head, current = _alembic_head_and_current()
            if head and head != current:
                logger.warning(
                    "Схема БД отстаёт от миграций: head=%s current=%s. "
                    "Запустите alembic upgrade head.",
                    head,
                    current,
                )
        else:
            head, current = _alembic_head_and_current()
            if head is None:
                raise RuntimeError(
                    "Миграции не найдены. Невозможно проверить схему — "
                    "убедитесь, что alembic/versions не пуст."
                )
            if current != head:
                raise RuntimeError(
                    "Схема БД не соответствует миграциям: "
                    f"head={head}, current={current}. Запустите `alembic upgrade head`."
                )
            logger.info(
                "База готова (Alembic). БД на head=%s, create_all отключён.", head
            )
    except RuntimeError:
        raise
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

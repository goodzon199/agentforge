from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config

from alembic import command

logger = logging.getLogger(__name__)


def _alembic_config() -> Config:
    """Point alembic at this service's alembic/ tree and real DATABASE_URL."""
    service_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(service_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(service_root / "alembic"))
    from app.core.config import settings

    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


def current_revision() -> str | None:
    from alembic.script import ScriptDirectory

    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    # Reuse env.py's head computation: this is the newest revision in the tree.
    heads = script.get_heads()
    return heads[0] if heads else None


def upgrade_to_head() -> str | None:
    """Run ``alembic upgrade head`` and return the new revision."""
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    return current_revision()

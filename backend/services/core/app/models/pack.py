from __future__ import annotations

import datetime as dt

from shared.pack import PackState
from sqlalchemy import JSON, Boolean, DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin


class Pack(UUIDPrimaryKeyMixin, Base):
    """A registered vertical pack (SDK manifest + lifecycle state).

    Core stores only the contract: manifest contents, base URL of the pack
    service and its lifecycle state. The pack itself keeps its own agents,
    workflows and migrations; core routes to it over the internal HTTP
    endpoint and never imports pack code.
    """

    __tablename__ = "packs"

    name: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    required_core_version: Mapped[str] = mapped_column(String(32), nullable=False, default=">=0.0.0")

    # Full manifest, kept as JSON so a newer pack version can be inspected
    # before it is enabled (upgrade_required flow).
    manifest: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    agents: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    permissions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    workflows: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    state: Mapped[PackState] = mapped_column(
        Enum(PackState, name="pack_state"),
        nullable=False,
        default=PackState.installed,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    last_healthcheck_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_health_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Sprint 5.2: per-pack configuration set by the operator (configure step).
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Pack {self.name}@{self.version} state={self.state.value}>"

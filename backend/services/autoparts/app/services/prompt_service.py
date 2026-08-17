from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import PromptVersion

# Built-in default system prompt for SalesAgent. When no PromptVersion row is
# active, agents fall back to these deterministic texts (sprint 3.2).
DEFAULT_SALES_PROMPT = (
    "Ты — SalesAgent, составляешь сообщение клиенту с вариантами товаров. "
    "Используй ТОЛЬКО данные из квоты (бренд, артикул, цена, срок, наличие). "
    "Не выдумывай товары, бренды, цены или сроки. Никогда не сообщай закупочную "
    "цену и наценку. Цены указывай в рублях с символом ₽ и пробелом между разрядами "
    "(например «8 950 ₽»). Формат: приветствие, список вариантов, вопрос, какой подходит. "
    "Верни только текст сообщения без кавычек и пояснений."
)

DEFAULT_PROMPTS: dict[str, str] = {
    "sales": DEFAULT_SALES_PROMPT,
}

# Demo versions created by seeding (idempotent). The pilot can compare quality
# across them and later run A/B tests.
DEMO_PROMPT_VERSIONS: dict[str, list[tuple[str, str, str, str]]] = {
    "sales": [
        (
            "v1",
            "Базовая версия",
            "Базовый SalesAgent: вежливое предложение вариантов по фактам квоты.",
            DEFAULT_SALES_PROMPT,
        ),
        (
            "v2",
            "Структурированный шаблон",
            "Строгая структура: приветствие, нумерованный список с ценой/сроком/наличием, "
            "выделение лучшего варианта, вопрос клиенту.",
            (
                "Ты — SalesAgent. Составь сообщение клиенту строго по структуре: "
                "1) приветствие; 2) нумерованный список вариантов из квоты (бренд, артикул, "
                "цена в ₽ с пробелами между разрядами, срок поставки, наличие); "
                "3) пометь лучший вариант значком ⭐; 4) вопрос, какой вариант подходит. "
                "Используй ТОЛЬКО данные из квоты. Не выдумывай товары, бренды, цены, сроки. "
                "Никогда не сообщай закупочную цену и наценку. Верни только текст сообщения."
            ),
        ),
    ],
}


class PromptService:
    """Manages versioned agent prompts (sprint 3.2).

    A company may override the global prompt with its own version for an agent
    kind; otherwise the active global version is used. Versioning is what makes
    quality comparison (and later A/B tests) possible.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Reads ------------------------------------------------------------

    def list(
        self,
        company_id: uuid.UUID | None = None,
        agent_kind: str | None = None,
    ) -> list[PromptVersion]:
        stmt = select(PromptVersion).order_by(
            PromptVersion.agent_kind.asc(), PromptVersion.version.asc()
        )
        if company_id is not None:
            stmt = stmt.where(
                or_(PromptVersion.company_id.is_(None), PromptVersion.company_id == company_id)
            )
        if agent_kind:
            stmt = stmt.where(PromptVersion.agent_kind == agent_kind)
        return list(self.db.scalars(stmt).unique().all())

    def get(self, prompt_id: uuid.UUID) -> PromptVersion | None:
        return self.db.get(PromptVersion, prompt_id)

    def active(
        self,
        agent_kind: str,
        company_id: uuid.UUID | None = None,
    ) -> PromptVersion | None:
        """The active prompt for an agent kind: company-specific wins, else global."""
        stmt = (
            select(PromptVersion)
            .where(PromptVersion.agent_kind == agent_kind)
            .where(PromptVersion.is_active.is_(True))
            .order_by(PromptVersion.company_id.is_(None).asc(), PromptVersion.created_at.desc())
        )
        if company_id is not None:
            stmt = stmt.where(
                or_(PromptVersion.company_id.is_(None), PromptVersion.company_id == company_id)
            )
        else:
            stmt = stmt.where(PromptVersion.company_id.is_(None))
        return self.db.scalars(stmt).first()

    def active_prompt(
        self,
        agent_kind: str,
        company_id: uuid.UUID | None = None,
    ) -> tuple[str, str | None]:
        """Return (content, version) for the active prompt, else the built-in
        default with version=None."""
        version = self.active(agent_kind, company_id)
        if version is not None:
            return version.content, version.version
        return DEFAULT_PROMPTS.get(agent_kind, ""), None

    # --- Writes -----------------------------------------------------------

    def create(
        self,
        *,
        company_id: uuid.UUID | None,
        agent_kind: str,
        version: str,
        name: str,
        content: str,
        description: str | None = None,
        is_active: bool = False,
    ) -> PromptVersion:
        existing = self._find(company_id, agent_kind, version)
        if existing is not None:
            return existing
        if is_active:
            self._deactivate(company_id, agent_kind)
        row = PromptVersion(
            company_id=company_id,
            agent_kind=agent_kind,
            version=version,
            name=name,
            description=description,
            content=content,
            is_active=is_active,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def activate(self, prompt: PromptVersion) -> PromptVersion:
        self._deactivate(prompt.company_id, prompt.agent_kind)
        prompt.is_active = True
        return prompt

    # --- Internals --------------------------------------------------------

    def _find(
        self,
        company_id: uuid.UUID | None,
        agent_kind: str,
        version: str,
    ) -> PromptVersion | None:
        stmt = (
            select(PromptVersion)
            .where(PromptVersion.agent_kind == agent_kind)
            .where(PromptVersion.version == version)
        )
        if company_id is None:
            stmt = stmt.where(PromptVersion.company_id.is_(None))
        else:
            stmt = stmt.where(PromptVersion.company_id == company_id)
        return self.db.scalars(stmt).first()

    def _deactivate(self, company_id: uuid.UUID | None, agent_kind: str) -> None:
        rows = self.list(company_id=company_id, agent_kind=agent_kind)
        for row in rows:
            if row.is_active:
                row.is_active = False

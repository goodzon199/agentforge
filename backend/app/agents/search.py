from __future__ import annotations

import uuid
from typing import Any

from app.agents.base import AgentOutput, BaseAgent
from app.models import PartRequest, Task
from app.services.parts_search_service import PartsSearchService
from app.services.task_service import TaskService

_VERB_PREFIXES = (
    "найди",
    "найти",
    "поищи",
    "поискать",
    "подбери",
    "подобрать",
    "поиск",
    "найди мне",
    "подскажи",
    "найд",
)


def extract_query(objective: str, input_data: dict[str, Any]) -> str:
    """Extract a search query from the task, stripping leading verbs."""
    query = (input_data.get("query") or "").strip()
    if query:
        return query
    text = objective.strip()
    lowered = text.lower()
    for prefix in _VERB_PREFIXES:
        if lowered.startswith(prefix):
            rest = text[len(prefix):].lstrip(": ,.!-— «»\"'").strip()
            if rest:
                return rest
    return text


class SearchAgent(BaseAgent):
    """
    Coordinator for the parts pipeline: for ``search_parts`` tasks it runs a
    concurrent search over the company's suppliers via PartsSearchService and
    hands the result to the pricing step. For ad-hoc queries it searches the
    company Knowledge Base (vector + keyword).
    """

    kind = "search"

    def execute(self, objective: str, input_data: dict[str, Any]) -> AgentOutput:
        part_request_id = input_data.get("part_request_id")
        if part_request_id:
            return self._search_parts(str(part_request_id))
        return self._search_knowledge(objective, input_data)

    # --- Parts pipeline ----------------------------------------------------

    def _search_parts(self, part_request_id: str) -> AgentOutput:
        if self.db is None:
            return AgentOutput(
                response="Поиск запчастей недоступен без базы данных.",
                data={"action": "search_parts_error", "reason": "db_missing"},
                routing_decision={"needs_agent": None, "reason": "db_missing", "engine": "search_parts"},
            )
        try:
            part_request = self.db.get(PartRequest, uuid.UUID(part_request_id))
        except (ValueError, TypeError):
            part_request = None
        if part_request is None:
            return AgentOutput(
                response="Заявка на запчасть не найдена.",
                data={"action": "search_parts_error", "reason": "not_found"},
                routing_decision={"needs_agent": None, "reason": "not_found", "engine": "search_parts"},
            )

        service = PartsSearchService(self.db)
        result = service.search(part_request, triggered_by="agent")
        pricing_task = self._create_pricing_task(part_request, result)
        if pricing_task is not None:
            # Lazy import to avoid a circular dependency (agents <-> orchestrator).
            from app.orchestrator.orchestrator import orchestrator

            orchestrator.submit(self.db, pricing_task)
        else:
            self.db.commit()

        response = (
            f"Поиск предложений завершён: найдено {result['offers_found']} "
            f"от {result['suppliers_succeeded']} поставщиков"
            + (f", {result['suppliers_failed']} недоступны" if result["suppliers_failed"] else "")
            + ". Передаю заявку в расчёт цены."
        )
        return AgentOutput(
            response=response,
            data={
                "action": "search_parts",
                "part_request_id": str(part_request.id),
                "run_id": str(result["run_id"]),
                "offers_found": result["offers_found"],
                "suppliers_succeeded": result["suppliers_succeeded"],
                "suppliers_failed": result["suppliers_failed"],
                "next_action": "pricing_parts",
                "pricing_task_id": str(pricing_task.id) if pricing_task else None,
            },
            routing_decision={
                "needs_agent": None,
                "reason": "Поиск выполнен SearchAgent по поставщикам.",
                "engine": "search_parts",
            },
            handoff_agent=None,
        )

    def _create_pricing_task(
        self, part_request: PartRequest, result: dict[str, Any]
    ) -> Task | None:
        """Hand-off contract: a pricing_parts task is created and submitted to
        the orchestrator, which runs the pricing engine (PricingAgent)."""
        if result["offers_found"] == 0:
            return None
        task = TaskService(self.db).create(
            company_id=part_request.company_id,
            title=f"Расчёт цены: {part_request.part_name}",
            objective="pricing_parts",
            input_data={
                "part_request_id": str(part_request.id),
                "run_id": str(result["run_id"]),
            },
        )
        self.db.add(task)
        self.db.flush()
        return task

    # --- Knowledge base search --------------------------------------------

    def _search_knowledge(self, objective: str, input_data: dict[str, Any]) -> AgentOutput:
        query = extract_query(objective, input_data)
        results = self._search(query)

        if results:
            lines = [f"По запросу «{query}» найдено записей: {len(results)}"]
            for entry, score in results:
                snippet = entry.content.replace("\n", " ").strip()
                if len(snippet) > 160:
                    snippet = snippet[:160] + "…"
                suffix = f" (схожесть {score:.2f})" if score is not None else ""
                lines.append(f"• {entry.title} — {snippet}{suffix}")
            response = "\n".join(lines)
            found = True
        else:
            response = (
                f"По запросу «{query}» ничего не найдено в базе знаний компании. "
                "Внешний поисковый провайдер (каталог/веб) пока не подключён."
            )
            found = False

        return AgentOutput(
            response=response,
            data={
                "action": "search_done",
                "query": query,
                "found": found,
                "mode": "vector" if results and results[0][1] is not None else "keyword",
                "results": [
                    {"title": e.title, "content": e.content, "tags": e.tags, "score": s}
                    for e, s in results
                ],
            },
            routing_decision={
                "needs_agent": None,
                "reason": "Поиск выполнен через SearchAgent по базе знаний.",
                "engine": "search",
            },
            handoff_agent=None,
        )

    def _search(self, query: str) -> list[tuple[Any, float | None]]:
        """Vector search first (semantic), keyword match as a fallback."""
        vector = self.memory.vector_search(self.record.company_id, query)
        if vector:
            return [(entry, score) for entry, score in vector]
        return [(entry, None) for entry in self._search_keywords(query)]

    def _search_keywords(self, query: str) -> list[Any]:
        """Case-insensitive match on title/content/tags over company knowledge."""
        entries = self.memory.knowledge(self.record.company_id, limit=100)
        needle = query.lower()
        return [
            e
            for e in entries
            if needle in e.title.lower()
            or needle in e.content.lower()
            or needle in " ".join(e.tags or []).lower()
        ]

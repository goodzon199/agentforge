from __future__ import annotations

from typing import Any

from app.agents.base import AgentOutput, BaseAgent

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
    Specialist for finding information. Searches the company Knowledge Base
    (KnowledgeEntry) by natural-language query. External search providers
    (catalog / web / parts) plug in later via the `search` tool.
    """

    kind = "search"

    def execute(self, objective: str, input_data: dict[str, Any]) -> AgentOutput:
        query = extract_query(objective, input_data)
        results = self._search_knowledge(query)

        if results:
            lines = [f"По запросу «{query}» найдено записей: {len(results)}"]
            for entry in results:
                snippet = entry.content.replace("\n", " ").strip()
                if len(snippet) > 160:
                    snippet = snippet[:160] + "…"
                lines.append(f"• {entry.title} — {snippet}")
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
                "results": [
                    {"title": e.title, "content": e.content, "tags": e.tags}
                    for e in results
                ],
            },
            routing_decision={
                "needs_agent": None,
                "reason": "Поиск выполнен через SearchAgent по базе знаний.",
                "engine": "search",
            },
            handoff_agent=None,
        )

    def _search_knowledge(self, query: str) -> list[Any]:
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

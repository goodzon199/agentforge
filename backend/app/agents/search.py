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

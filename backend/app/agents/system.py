from __future__ import annotations

import json
import re
from typing import Any

from app.agents.base import AgentOutput, BaseAgent
from app.llm.types import LLMMessage

# Deterministic routing (used when no LLM provider is configured).
_ROUTING_RULES: list[tuple[list[str], str]] = [
    (
        ["найд", "поиск", "search", "подбер", "тормозн", "запчаст", "колод", "каталог", "артикул"],
        "SearchAgent",
    ),
    (
        ["отправь письмо", "отправь на почту", "email", "письмо", "напиши на почту", "e-mail"],
        "EmailAgent",
    ),
]


class SystemAgent(BaseAgent):
    """
    The first agent of the platform.

    It knows how to do exactly one thing for now:
      * receives a task (e.g. "Найди тормозные колодки")
      * decides which specialized agent is required
      * answers e.g. "Для выполнения нужен SearchAgent"

    This establishes the communication / routing contract between agents.
    """

    kind = "system"

    def execute(self, objective: str, input_data: dict[str, Any]) -> AgentOutput:
        context = self.recall_context()

        if self.llm.available:
            decision = self._route_with_llm(objective, context)
        else:
            decision = self._route_deterministic(objective)

        handoff = decision.get("needs_agent")
        if handoff:
            response = f"Для выполнения этой задачи нужен {handoff}."
        else:
            response = decision.get(
                "answer",
                "Я получил задачу и зафиксировал её. Для выполнения понадобится профильный агент.",
            )

        return AgentOutput(
            response=response,
            data={
                "objective": objective,
                "memory_context": {
                    "short_memories": len(context.get("short", [])),
                    "long_memories": len(context.get("long", [])),
                },
            },
            routing_decision=decision,
            handoff_agent=handoff,
        )

    # --- Routing ----------------------------------------------------------

    def _route_deterministic(self, objective: str) -> dict[str, Any]:
        text = objective.lower()
        for keywords, agent_name in _ROUTING_RULES:
            if any(kw in text for kw in keywords):
                return {
                    "needs_agent": agent_name,
                    "reason": f"Задача содержит маркеры {keywords[:2]} и относится к области «{agent_name}».",
                    "engine": "rules",
                }
        return {
            "needs_agent": None,
            "reason": "Задача не требует специализированного агента.",
            "engine": "rules",
        }

    def _route_with_llm(self, objective: str, context: dict[str, object]) -> dict[str, Any]:
        system_prompt = (
            "Ты — SystemAgent, диспетчер платформы цифровых сотрудников. "
            "Твоя задача — классифицировать входящую задачу и решить, какой "
            "специализированный агент нужен для её выполнения. "
            "Отвечай строго в формате JSON: "
            '{"needs_agent": "<имя агента или null>", "reason": "<почему>", "answer": "<краткий ответ пользователю>"}. '
            "Известные агенты: SearchAgent (поиск товаров/запчастей/информации), EmailAgent (отправка писем)."
        )
        user_prompt = (
            f"Задача: {objective}\n"
            f"Память агента: {json.dumps(context, ensure_ascii=False)[:2000]}"
        )
        try:
            result = self.llm.chat(
                messages=[
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=user_prompt),
                ],
                model=self.record.model,
                temperature=self.record.temperature,
                max_tokens=300,
            )
        except Exception:
            # LLM провайдер недоступен/отклонил запрос — откатываемся на правила.
            return self._route_deterministic(objective)

        if result is None:
            return self._route_deterministic(objective)

        match = re.search(r"\{.*\}", result.content, re.DOTALL)
        if not match:
            return {"needs_agent": None, "reason": "LLM вернул некорректный ответ.", "engine": "llm"}
        try:
            return {**json.loads(match.group(0)), "engine": "llm"}
        except json.JSONDecodeError:
            return {"needs_agent": None, "reason": "LLM вернул невалидный JSON.", "engine": "llm"}

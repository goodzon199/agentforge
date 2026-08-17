from __future__ import annotations

import json
import re
from typing import Any

from app.agents.base import AgentOutput, BaseAgent
from app.llm.types import LLMMessage

# Deterministic routing (used when no LLM provider is configured).
_ROUTING_RULES: list[tuple[list[str], str]] = [
    (
        ["process_customer_message"],
        "IntakeAgent",
    ),
    (
        ["pricing_parts"],
        "PricingAgent",
    ),
    (
        ["sales_draft", "подготовь предложение", "предложение клиенту", "sales"],
        "SalesAgent",
    ),
    (
        ["search_parts"],
        "SearchAgent",
    ),
    (
        ["найд", "поиск", "search", "подбер", "тормозн", "запчаст", "колод", "каталог", "артикул"],
        "SearchAgent",
    ),
    (
        ["send_email", "отправь письмо", "отправь на почту", "email", "письмо", "напиши на почту", "e-mail"],
        "EmailAgent",
    ),
]

# Internal pipeline objectives are always routed deterministically so the
# vertical slice (message -> intake -> search -> pricing -> sales) does not
# depend on LLM mood.
_INTERNAL_OBJECTIVES = frozenset(
    {"process_customer_message", "search_parts", "pricing_parts", "sales_draft", "send_email"}
)


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
        decision = self._route(objective, context)

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

    def _route(self, objective: str, context: dict[str, object]) -> dict[str, Any]:
        # Internal pipeline commands are always deterministic.
        if objective.strip().lower() in _INTERNAL_OBJECTIVES:
            return self._route_deterministic(objective)
        # Deterministic keyword rules win over the LLM: internal commands must
        # never depend on LLM mood (a free-text objective like "отправь письмо"
        # is still an internal command and must reach the right agent).
        rule_hit = self._route_deterministic(objective)
        if rule_hit.get("needs_agent"):
            return rule_hit
        # Only unrecognized external free text may consult the LLM.
        if self.llm.available:
            return self._route_with_llm(objective, context)
        return rule_hit

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
            "Известные агенты: IntakeAgent (обработка входящих сообщений клиентов и оформление заявок на запчасти), "
            "SearchAgent (поиск товаров/запчастей/информации), "
            "PricingAgent (расчёт цены по предложениям поставщиков), "
            "SalesAgent (подготовка предложения клиенту по готовой квоте), "
            "EmailAgent (отправка писем)."
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

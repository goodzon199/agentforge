from __future__ import annotations

from typing import Any

from app.agents.base import AgentOutput, BaseAgent
from app.core.config import settings
from app.reliability.errors import FailureKind


class EmailDeliveryError(RuntimeError):
    """SMTP send failed. Carries a normalized ``kind`` so the orchestrator can
    decide retry (transient) vs dead-letter (definitive)."""

    def __init__(self, message: str, *, kind: FailureKind) -> None:
        super().__init__(message)
        self.kind = kind


class EmailAgent(BaseAgent):
    """
    Sends e-mail on behalf of the platform. Receives a task handed off
    by SystemAgent and turns it into an SMTP message via the email tool.

    A failed send fails the task (with a normalized failure kind), so the
    orchestrator can retry transient SMTP outages and dead-letter definitive
    ones — nothing is silently lost (sprint 3.5).
    """

    kind = "email"

    def execute(self, objective: str, input_data: dict[str, Any]) -> AgentOutput:
        to = (input_data.get("to") or "").strip() or settings.email_default_to
        subject = (
            (input_data.get("subject") or "").strip()
            or f"Задача: {objective[:60]}"
        )
        body = (input_data.get("body") or "").strip() or objective

        result = self.tools.run("email", to=to, subject=subject, body=body)

        if not result.ok:
            kind = FailureKind.INTERNAL_ERROR
            if isinstance(result.data, dict):
                try:
                    kind = FailureKind(result.data.get("kind") or "internal_error")
                except ValueError:
                    kind = FailureKind.INTERNAL_ERROR
            raise EmailDeliveryError(
                f"Не удалось отправить письмо: {result.error}", kind=kind
            )

        sent = result.data
        response = f"Письмо отправлено на {sent['to']} (тема: «{sent['subject']}»)."

        return AgentOutput(
            response=response,
            data={
                "action": "email_sent",
                "to": sent["to"],
                "subject": sent["subject"],
                "transport": sent["transport"],
            },
            routing_decision={
                "needs_agent": None,
                "reason": "Письмо доставлено через EmailAgent.",
                "engine": "email",
            },
            handoff_agent=None,
        )

from __future__ import annotations

from typing import Any

from app.agents.base import AgentOutput, BaseAgent
from app.core.config import settings


class EmailAgent(BaseAgent):
    """
    Sends e-mail on behalf of the platform. Receives a task handed off
    by SystemAgent and turns it into an SMTP message via the email tool.
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
            return AgentOutput(
                response=f"Не удалось отправить письмо: {result.error}",
                data={"error": result.error, "to": to},
                routing_decision={"needs_agent": None, "reason": result.error, "engine": "email"},
                handoff_agent=None,
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

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.core.config import settings
from app.tools.base import BaseTool, ToolResult


class EmailTool(BaseTool):
    """
    Sends an e-mail over SMTP. In the demo stack this points to MailHog
    (http://localhost:8025); point SMTP_HOST to a real server in production.
    """

    name = "email"
    description = "Отправить письмо на e-mail (SMTP)."
    version = "2.0.0"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["to", "subject", "body"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        to = (kwargs.get("to") or settings.email_default_to).strip()
        subject = kwargs.get("subject") or "(без темы)"
        body = kwargs.get("body") or ""

        if not settings.smtp_host:
            return ToolResult(
                ok=False,
                error="SMTP не настроен. Укажите SMTP_HOST (например, mailhog) в .env.",
            )

        msg = MIMEMultipart("alternative")
        msg["From"] = settings.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(body.replace("\n", "<br>\n"), "html", "utf-8"))

        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_from, [to], msg.as_string())
        except Exception as exc:
            return ToolResult(ok=False, error=f"Ошибка отправки SMTP: {exc}")

        return ToolResult(
            ok=True,
            data={
                "to": to,
                "subject": subject,
                "from": settings.smtp_from,
                "transport": f"{settings.smtp_host}:{settings.smtp_port}",
            },
        )

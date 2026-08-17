from __future__ import annotations

import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, ClassVar

from app.core.config import settings
from app.reliability.circuit_breaker import get_breaker
from app.reliability.errors import FailureKind, classify_exception
from app.reliability.retry import RetryPolicy, get_policy
from app.tools.base import BaseTool, ToolResult


class EmailTool(BaseTool):
    """
    Sends an e-mail over SMTP. In the demo stack this points to MailHog
    (http://localhost:8025); point SMTP_HOST to a real server in production.
    """

    name = "email"
    description = "Отправить письмо на e-mail (SMTP)."
    version = "2.0.0"
    input_schema: ClassVar[dict[str, Any]] = {
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
                data={"kind": FailureKind.INTERNAL_ERROR.value},
            )

        # Circuit breaker "smtp": fail fast when the relay is down instead of
        # blocking the agent on a connect timeout for every send.
        breaker = get_breaker("smtp")
        if not breaker.allow_request():
            return ToolResult(
                ok=False,
                error="SMTP недоступен: circuit breaker открыт. Отправка будет повторена позже.",
                data={"kind": FailureKind.UNAVAILABLE.value},
            )

        msg = MIMEMultipart("alternative")
        msg["From"] = settings.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(body.replace("\n", "<br>\n"), "html", "utf-8"))

        policy = get_policy("smtp")
        last_error: Exception | None = None
        for attempt in range(1, policy.max_attempts + 1):
            try:
                with smtplib.SMTP(
                    settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout
                ) as server:
                    if settings.smtp_user:
                        server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(settings.smtp_from, [to], msg.as_string())
                breaker.record_success()
                return ToolResult(
                    ok=True,
                    data={
                        "to": to,
                        "subject": subject,
                        "from": settings.smtp_from,
                        "transport": f"{settings.smtp_host}:{settings.smtp_port}",
                    },
                )
            except Exception as exc:
                last_error = exc
                kind = classify_exception(exc)
                if policy.should_retry(kind, attempt):
                    time.sleep(policy.next_delay(attempt))
                    continue
                break
        if RetryPolicy.is_transient(classify_exception(last_error)):
            breaker.record_failure()
        return ToolResult(
            ok=False,
            error=f"Ошибка отправки SMTP: {last_error}",
            data={"kind": classify_exception(last_error).value},
        )

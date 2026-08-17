from __future__ import annotations

import logging
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

logger = logging.getLogger("agentforge.request")


class SecurityHeadersMiddleware:
    """Add security-relevant response headers. CSP and HSTS apply only in
    production (development keeps Swagger UI / local tooling working)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Permissions-Policy"] = (
                    "camera=(), microphone=(), geolocation=()"
                )
                if settings.environment == "production":
                    headers["Strict-Transport-Security"] = (
                        "max-age=31536000; includeSubDomains"
                    )
                    if settings.security_csp:
                        headers["Content-Security-Policy"] = settings.security_csp
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RequestBodySizeLimitMiddleware:
    """Reject request bodies larger than the configured limit with a 413."""

    def __init__(self, app: ASGIApp, max_bytes: int | None = None) -> None:
        self.app = app
        self.max_bytes = (
            max_bytes if max_bytes is not None else settings.max_request_body_bytes
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = None
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
        if declared is not None and declared > self.max_bytes:
            await _plain_response(send, 413, "Request body too large")
            return

        received = 0

        async def receive_wrapper() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLarge(received, self.max_bytes)
            return message

        try:
            await self.app(scope, receive_wrapper, send)
        except BodyTooLarge:
            await _plain_response(send, 413, "Request body too large")


class BodyTooLarge(Exception):
    def __init__(self, received: int, limit: int) -> None:
        super().__init__(f"Body {received} bytes exceeds limit {limit}")


class RequestLoggingMiddleware:
    """Log every HTTP request with a correlation id and duration."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Reuse the id the (outer) audit-context middleware assigned so the
        # access log and audit journal share one correlation id.
        from app.services.audit_context import get_audit_context

        ctx = get_audit_context()
        request_id = ctx.request_id if ctx else uuid.uuid4().hex[:12]
        start = time.perf_counter()
        status_code = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Request-ID", request_id)
            await send(message)

        method = scope.get("method", "")
        path = scope.get("path", "")
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "%s %s -> %s %.1fms id=%s",
                method,
                path,
                status_code or "-",
                duration_ms,
                request_id,
            )


class AuditContextMiddleware:
    """Capture request metadata into the per-request audit context.

    The outermost middleware: it assigns the correlation id (echoed back as
    ``X-Request-ID`` and reused by the access log) and records the client IP
    and user-agent so ``AuditService`` can attach them to every record — the
    audit layer never touches FastAPI types.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from app.services.audit_context import (
            AuditContext,
            reset_audit_context,
            set_audit_context,
        )

        headers: dict[str, str] = {}
        for name, value in scope.get("headers", []):
            headers[name.decode("latin1").lower()] = value.decode("latin1")
        request_id = headers.get("x-request-id") or uuid.uuid4().hex[:12]
        client = scope.get("client")
        ctx = AuditContext(
            request_id=request_id,
            ip_address=client[0] if client else None,
            user_agent=headers.get("user-agent"),
        )
        token = set_audit_context(ctx)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                mheaders = MutableHeaders(scope=message)
                mheaders.setdefault("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            reset_audit_context(token)


async def _plain_response(
    send: Send, status_code: int, detail: str
) -> None:
    body = f'{{"detail":"{detail}"}}'.encode()
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})

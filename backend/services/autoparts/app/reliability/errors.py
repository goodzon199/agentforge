from __future__ import annotations

import enum


class FailureKind(str, enum.Enum):
    """Canonical failure vocabulary shared by agents and the dashboard (sprint 3.5).

    Every subsystem (LLM, suppliers, SMTP, task runner) classifies its errors
    into one of these codes, so analytics and operators speak one language:
    a timeout is always ``timeout`` whether it came from Ollama, Rossko or
    the SMTP relay.
    """

    OK = "ok"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION = "authentication"
    PERMISSION_DENIED = "permission_denied"
    INVALID_RESPONSE = "invalid_response"
    SUPPLIER_ERROR = "supplier_error"
    INTERNAL_ERROR = "internal_error"


# Only these are worth retrying: the service was reachable but flaky, or the
# request never completed. Definitive failures (bad credentials, malformed
# answers, permission problems) must not be retried.
TRANSIENT = frozenset(
    {
        FailureKind.TIMEOUT,
        FailureKind.UNAVAILABLE,
        FailureKind.RATE_LIMITED,
    }
)

# The eight failure codes as plain strings (analytics / API serialization).
FAILURE_CODES = tuple(k.value for k in FailureKind if k is not FailureKind.OK)

_ALL_KINDS = {k.value: k for k in FailureKind}


def from_llm_status(status: str) -> FailureKind:
    """Map a persisted LLMUsage.status string to a canonical failure code."""
    return _ALL_KINDS.get(status or "", FailureKind.INTERNAL_ERROR)


def from_llm_kind(kind) -> FailureKind:
    """Map an :class:`app.llm.errors.LLMErrorKind` to a canonical code."""
    from app.llm.errors import LLMErrorKind

    mapping = {
        LLMErrorKind.OK: FailureKind.OK,
        LLMErrorKind.TIMEOUT: FailureKind.TIMEOUT,
        LLMErrorKind.UNAVAILABLE: FailureKind.UNAVAILABLE,
        LLMErrorKind.RATE_LIMITED: FailureKind.RATE_LIMITED,
        LLMErrorKind.AUTHENTICATION: FailureKind.AUTHENTICATION,
        LLMErrorKind.PERMISSION_DENIED: FailureKind.PERMISSION_DENIED,
        LLMErrorKind.INVALID_RESPONSE: FailureKind.INVALID_RESPONSE,
        LLMErrorKind.ERROR: FailureKind.INTERNAL_ERROR,
    }
    return mapping.get(kind, FailureKind.INTERNAL_ERROR)


def from_supplier_kind(kind: str | None) -> FailureKind:
    """Map a supplier error kind (``SupplierAdapterError.kind``) to a code."""
    mapping = {
        "connection": FailureKind.UNAVAILABLE,
        "timeout": FailureKind.TIMEOUT,
        "auth": FailureKind.AUTHENTICATION,
        "rate_limit": FailureKind.RATE_LIMITED,
        "response": FailureKind.SUPPLIER_ERROR,
        "parse": FailureKind.INVALID_RESPONSE,
        "supplier_error": FailureKind.SUPPLIER_ERROR,
    }
    return mapping.get(kind or "", FailureKind.SUPPLIER_ERROR)


def classify_exception(exc: BaseException) -> FailureKind:
    """Generic exception -> canonical code (task runner / SMTP / unknown)."""
    # A caller may attach an explicit, already-normalized code.
    explicit = getattr(exc, "kind", None)
    if isinstance(explicit, FailureKind):
        return explicit

    name = type(exc).__name__

    # httpx timeouts
    if name in {"ReadTimeout", "WriteTimeout", "ConnectTimeout", "PoolTimeout"}:
        return FailureKind.TIMEOUT

    # sockets / connection refused / network unreachable
    if name in {"ConnectError", "ConnectionError", "RemoteProtocolError", "ConnectionRefusedError"}:
        return FailureKind.UNAVAILABLE
    if isinstance(exc, OSError):
        import errno
        import socket

        if exc.errno in (errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ECONNRESET):
            return FailureKind.UNAVAILABLE
        if exc.errno == errno.ETIMEDOUT:
            return FailureKind.TIMEOUT
        # getaddrinfo failures: DNS down / host unknown are infrastructure
        # problems worth retrying, not business errors.
        if isinstance(exc, socket.gaierror) and exc.errno in (
            socket.EAI_NONAME,
            socket.EAI_AGAIN,
            socket.EAI_FAIL,
        ):
            return FailureKind.UNAVAILABLE

    # SMTP transport (smtplib)
    if name in {"SMTPConnectError", "SMTPServerDisconnected", "SMTPResponseException"}:
        return FailureKind.UNAVAILABLE
    if name == "SMTPAuthenticationError":
        return FailureKind.AUTHENTICATION

    # HTTP error with a status code
    status = getattr(exc, "status_code", None)
    if status is not None:
        if status in (401,):
            return FailureKind.AUTHENTICATION
        if status in (403,):
            return FailureKind.PERMISSION_DENIED
        if status == 429:
            return FailureKind.RATE_LIMITED
        if status >= 500:
            return FailureKind.UNAVAILABLE

    if name in {"AuthenticationError", "LoginError"}:
        return FailureKind.AUTHENTICATION
    if name in {"PermissionDeniedError", "ForbiddenError"}:
        return FailureKind.PERMISSION_DENIED

    return FailureKind.INTERNAL_ERROR

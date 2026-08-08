from __future__ import annotations

import enum
import socket

from app.llm.types import LLMResponse


class LLMErrorKind(str, enum.Enum):
    """Normalized outcome of a single LLM attempt.

    These codes are the only reasons analytics ever sees — never raw
    exception classes — so the pilot can distinguish a timeout from an
    outage from a rate limit from a malformed answer.
    """

    OK = "ok"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    INVALID_RESPONSE = "invalid_response"
    ERROR = "error"


# Only these are worth retrying: the service was reachable but flaky, or a
# request never completed. Business errors (bad key, 4xx, malformed answer)
# are definitive and must not be retried.
TRANSIENT = frozenset(
    {LLMErrorKind.TIMEOUT, LLMErrorKind.UNAVAILABLE, LLMErrorKind.RATE_LIMITED}
)


def classify_exception(exc: BaseException) -> LLMErrorKind:
    """Map a raw provider exception to a normalized outcome code."""
    name = type(exc).__name__

    # httpx timeout family
    if isinstance(exc, socket.timeout):
        return LLMErrorKind.TIMEOUT
    if name in {"ReadTimeout", "WriteTimeout", "ConnectTimeout", "PoolTimeout"}:
        return LLMErrorKind.TIMEOUT

    # openai SDK timeout / connection errors
    if name == "APITimeoutError":
        return LLMErrorKind.TIMEOUT
    if name == "APIConnectionError":
        return LLMErrorKind.UNAVAILABLE

    # rate limiting (openai.RateLimitError wraps an APIStatusError with 429)
    if name == "RateLimitError":
        return LLMErrorKind.RATE_LIMITED

    # openai.APIStatusError carries an HTTP status on the response
    if name == "APIStatusError":
        status = getattr(exc, "status_code", None)
        if status == 429:
            return LLMErrorKind.RATE_LIMITED
        if status in (502, 503, 504):
            return LLMErrorKind.UNAVAILABLE
        return LLMErrorKind.ERROR

    if name in {"AuthenticationError", "PermissionDeniedError"}:
        return LLMErrorKind.UNAVAILABLE

    if name in {"ConnectError", "ConnectionError", "RemoteProtocolError"}:
        return LLMErrorKind.UNAVAILABLE

    return LLMErrorKind.ERROR


def classify_response(response: LLMResponse | None) -> LLMErrorKind:
    """A completed attempt may still be unusable (empty answer)."""
    if response is None:
        return LLMErrorKind.ERROR
    return LLMErrorKind.OK if response.content else LLMErrorKind.INVALID_RESPONSE

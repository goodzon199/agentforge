"""Per-user business rate limits (sprint 3.7.1).

Authenticated API calls are bucketed into READ / WRITE / EXPENSIVE / AI
categories derived from the request method + path, each with its own
per-company-per-user quota enforced in Redis (with an in-memory fallback).
PUBLIC is keyed by client IP and guards the login + public web-chat endpoints.

Keys are scoped so that a burst from one user can never block another tenant:
``agentos:rate:biz:<category>:<company_id>:<user_id>``.
"""

from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from app.core.rate_limit import RateLimiter

# Path markers that identify heavy work. AI comes first: endpoints that drive
# an LLM call or spawn the agent pipeline. EXPENSIVE covers network-bound
# supplier work (search / live test / pricing) that bypasses the LLM.
_AI_PATH_MARKERS = ("/sales-draft", "/prepare", "/memory", "/replay")
_EXPENSIVE_PATH_MARKERS = ("/search", "/test", "/price")


def category_for(method: str, path: str) -> str:
    """Map a request to its rate-limit category.

    Rules (checked in order):
      * path mentions an AI marker          -> "ai"
      * path mentions an EXPENSIVE marker   -> "expensive"
      * GET                                 -> "read"
      * anything else (mutations)           -> "write"
    """
    lowered = path.lower()
    if any(marker in lowered for marker in _AI_PATH_MARKERS):
        return "ai"
    if any(marker in lowered for marker in _EXPENSIVE_PATH_MARKERS):
        return "expensive"
    if method.upper() == "GET":
        return "read"
    return "write"


class BusinessRateLimiter:
    """Fixed-window quotas per category, keyed by tenant + actor."""

    _DEFAULT_LIMIT = 120
    _DEFAULT_WINDOW = 60

    def __init__(self, limiter: RateLimiter | None = None) -> None:
        self.limiter = limiter or RateLimiter()
        from app.core.config import settings

        self._settings = settings

    def _config(self, category: str) -> tuple[int, int]:
        cfg = self._settings.business_rate_limits.get(category) or self._settings.business_rate_limits.get(
            "write", {}
        )
        return (
            int(cfg.get("limit", self._DEFAULT_LIMIT)),
            int(cfg.get("window", self._DEFAULT_WINDOW)),
        )

    @staticmethod
    def key(category: str, company_id: UUID | None, user_id: UUID) -> str:
        return f"agentos:rate:biz:{category}:{company_id}:{user_id}"

    @staticmethod
    def public_key(category: str, ip: str) -> str:
        return f"agentos:rate:biz:{category}:ip:{ip}"

    def check(self, *, category: str, company_id: UUID | None, user_id: UUID) -> tuple[bool, int]:
        """Record one call; returns (allowed, retry_after_seconds)."""
        limit, window = self._config(category)
        key = self.key(category, company_id, user_id)
        allowed = self.limiter.hit(key, limit, window)
        return allowed, self.limiter.retry_after_seconds(key, window)

    def check_public(self, *, category: str, ip: str) -> tuple[bool, int]:
        limit, window = self._config(category)
        key = self.public_key(category, ip)
        allowed = self.limiter.hit(key, limit, window)
        return allowed, self.limiter.retry_after_seconds(key, window)


@lru_cache
def get_business_rate_limiter() -> BusinessRateLimiter:
    return BusinessRateLimiter()

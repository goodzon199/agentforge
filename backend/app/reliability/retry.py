from __future__ import annotations

import random
from dataclasses import dataclass

from app.reliability.errors import TRANSIENT, FailureKind


@dataclass
class RetryPolicy:
    """Shared retry decision for every external call (sprint 3.5).

    The policy only decides *whether* to retry and *how long* to wait —
    transient errors only, exponential backoff with full jitter. The caller
    keeps its own attempt recording (e.g. LLMUsage rows, supplier attempts),
    but the retry logic lives in one place with per-service overrides.
    """

    max_attempts: int = 2
    initial_delay: float = 0.5
    max_delay: float = 3.0
    factor: float = 2.0
    jitter: bool = True

    @staticmethod
    def is_transient(kind: FailureKind) -> bool:
        return kind in TRANSIENT

    def should_retry(self, kind: FailureKind, attempt: int) -> bool:
        """Whether a failed attempt should be retried.

        ``attempt`` is 1-based (the attempt that just failed).
        """
        return attempt < self.max_attempts and kind in TRANSIENT

    def next_delay(self, attempt: int) -> float:
        """Exponential backoff (with jitter) before retry ``attempt``.

        ``attempt`` is the retry number (1 = first retry).
        """
        base = min(self.initial_delay * (self.factor ** (attempt - 1)), self.max_delay)
        if self.jitter:
            return random.uniform(0, base)
        return base


def get_policy(service: str) -> RetryPolicy:
    """Build a retry policy for a service, honoring per-service overrides.

    Services: ``llm``, ``rossko``, ``http``, ``smtp``. Overrides come from
    ``settings.retry_policies[service]`` (e.g. ``{"max_attempts": 3}``); the
    LLM service keeps its dedicated settings from hotfix 3.4.1.
    """
    from app.core.config import settings

    overrides = dict(settings.retry_policies.get(service) or {})
    if service == "llm":
        base = {
            "max_attempts": settings.llm_max_attempts,
            "initial_delay": settings.llm_retry_initial_delay,
            "max_delay": settings.llm_retry_max_delay,
        }
    else:
        base = {
            "max_attempts": settings.retry_max_attempts,
            "initial_delay": settings.retry_initial_delay,
            "max_delay": settings.retry_max_delay,
        }
    base.update(overrides)
    return RetryPolicy(
        max_attempts=int(base["max_attempts"]),
        initial_delay=float(base["initial_delay"]),
        max_delay=float(base["max_delay"]),
    )

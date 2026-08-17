"""Global emergency switch (sprint 3.7.1).

Lets an operator pause ALL agentic work with one call: while engaged, the
orchestrator workers stop consuming the task queue, new tasks and replays are
rejected, and the public web-chat stops accepting messages. Existing in-flight
work is allowed to finish; nothing new starts.

State lives in Redis (``agentos:emergency:off``) so every worker process sees
the same view, with an in-memory fallback for tests / when Redis is down.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from app.core.redis import redis_client

_KEY = "agentos:emergency:off"


class EmergencySwitch:
    """Redis-backed kill-switch with an in-process fallback."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Fallback state when Redis is unreachable: (engaged_at_monotonic, reason).
        self._local: dict[str, tuple[float, str]] = {}

    def engage(self, reason: str) -> None:
        reason = (reason or "").strip()
        if redis_client.available:
            redis_client.set_json(
                _KEY,
                {
                    "reason": reason,
                    "engaged_at": datetime.now(UTC).isoformat(),
                },
            )
        with self._lock:
            self._local[_KEY] = (time.monotonic(), reason)

    def release(self) -> None:
        if redis_client.available:
            redis_client.delete(_KEY)
        with self._lock:
            self._local.pop(_KEY, None)

    def status(self) -> dict:
        if redis_client.available:
            raw = redis_client.get_json(_KEY)
            if raw:
                return {
                    "engaged": True,
                    "reason": raw.get("reason"),
                    "engaged_at": raw.get("engaged_at"),
                }
            return {"engaged": False, "reason": None, "engaged_at": None}
        with self._lock:
            entry = self._local.get(_KEY)
            if entry is None:
                return {"engaged": False, "reason": None, "engaged_at": None}
            return {"engaged": True, "reason": entry[1], "engaged_at": None}

    def is_engaged(self) -> bool:
        return bool(self.status()["engaged"])


emergency_switch = EmergencySwitch()

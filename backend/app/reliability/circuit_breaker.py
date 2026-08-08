from __future__ import annotations

import enum
import threading
import time
from typing import Any


class BreakerState(str, enum.Enum):
    """Lifecycle of a circuit breaker (sprint 3.5)."""

    closed = "closed"
    open = "open"
    half_open = "half_open"


class CircuitBreaker:
    """Per-service circuit breaker.

    States:
      * CLOSED    — requests flow; failures are counted.
      * OPEN      — after ``failure_threshold`` consecutive-ish failures the
        breaker trips: callers fail fast instead of waiting for a timeout.
      * HALF_OPEN — after ``recovery_timeout`` the breaker lets a small number
        of probe calls through; one success closes it, one failure re-opens it.

    Thread-safe (used from worker threads and the API process).
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.name = name
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_timeout = max(0.1, float(recovery_timeout))
        self.half_open_max_calls = max(1, int(half_open_max_calls))

        self._lock = threading.RLock()
        self._state = BreakerState.closed
        self._failures = 0
        self._successes = 0
        self._opened_at: float | None = None
        self._opened_wall: float | None = None
        self._open_count = 0
        self._half_open_in_flight = 0

    # --- API ---------------------------------------------------------------

    @property
    def state(self) -> BreakerState:
        with self._lock:
            return self._state

    def allow_request(self) -> bool:
        """Whether a new call may proceed right now (fail-fast gate)."""
        with self._lock:
            now = time.monotonic()
            if self._state is BreakerState.closed:
                return True
            if self._state is BreakerState.open:
                if self._opened_at is not None and now - self._opened_at >= self.recovery_timeout:
                    self._state = BreakerState.half_open
                    self._half_open_in_flight = 0
                    return self._take_half_open_slot()
                return False
            # half_open
            return self._take_half_open_slot()

    def record_success(self) -> None:
        with self._lock:
            self._successes += 1
            if self._state is BreakerState.half_open:
                self._state = BreakerState.closed
                self._failures = 0
                self._opened_at = None
                self._opened_wall = None
                self._half_open_in_flight = 0
            elif self._state is BreakerState.closed:
                # rolling window: drop old failures on a clean streak
                if self._successes % self.failure_threshold == 0:
                    self._failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state is BreakerState.closed and self._failures >= self.failure_threshold:
                self._open()
            elif self._state is BreakerState.half_open:
                self._open()

    def _open(self) -> None:
        self._state = BreakerState.open
        self._opened_at = time.monotonic()
        self._opened_wall = _wall_clock()
        self._open_count += 1
        self._half_open_in_flight = 0

    def _take_half_open_slot(self) -> bool:
        if self._half_open_in_flight < self.half_open_max_calls:
            self._half_open_in_flight += 1
            return True
        return False

    def reset(self) -> None:
        with self._lock:
            self._state = BreakerState.closed
            self._failures = 0
            self._successes = 0
            self._opened_at = None
            self._opened_wall = None
            self._half_open_in_flight = 0

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout_seconds": round(self.recovery_timeout, 2),
                "failures": self._failures,
                "successes": self._successes,
                "open_count": self._open_count,
                "opened_at": _iso(self._opened_wall),
            }


class _BreakerRegistry:
    """Named breakers shared process-wide (ollama / rossko / smtp / http)."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.RLock()

    def get(self, name: str) -> CircuitBreaker:
        from app.core.config import settings

        with self._lock:
            breaker = self._breakers.get(name)
            if breaker is None:
                override = dict(settings.circuit_breaker_overrides.get(name) or {})
                breaker = CircuitBreaker(
                    name,
                    failure_threshold=override.get(
                        "failure_threshold", settings.circuit_breaker_failure_threshold
                    ),
                    recovery_timeout=override.get(
                        "recovery_timeout", settings.circuit_breaker_recovery_timeout
                    ),
                    half_open_max_calls=override.get(
                        "half_open_max_calls", settings.circuit_breaker_half_open_max_calls
                    ),
                )
                self._breakers[name] = breaker
            return breaker

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._breakers)

    def snapshots(self) -> list[dict[str, Any]]:
        with self._lock:
            return [b.snapshot() for b in self._breakers.values()]


breaker_registry = _BreakerRegistry()


def get_breaker(name: str) -> CircuitBreaker:
    return breaker_registry.get(name)


def _iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _wall_clock() -> float:
    """Wall-clock seconds (epoch) — for ``opened_at`` in snapshots.

    ``time.monotonic()`` must not be converted to a datetime (it is offset
    from boot, not from the epoch); store both internally.
    """
    return time.time()

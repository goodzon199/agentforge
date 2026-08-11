from __future__ import annotations

import enum
import threading
import time
import uuid
from typing import Any

from app.core.config import settings

# External services protected by a circuit breaker. The registry can show a
# snapshot for all of them even when the current process never touched one.
BREAKER_NAMES = ("ollama", "rossko", "smtp", "http")


class BreakerState(str, enum.Enum):
    """Lifecycle of a circuit breaker (sprint 3.5)."""

    closed = "closed"
    open = "open"
    half_open = "half_open"


# --- Redis-backed state -------------------------------------------------------
#
# Distributed breaker (sprint 3.5.1): the state lives in Redis so every worker
# process shares one view and a breaker opened by process A is respected by
# process B (and by the health/analytics endpoints).
#
#   agentos:breaker:<name>         -> JSON state, EXPIRE'd (resets when idle)
#   agentos:breaker:<name>:probe   -> HALF_OPEN distributed lock (SET NX PX)
#
# All transitions are atomic via Lua scripts (no WATCH/MULTI retry loops):
# CLOSED -> OPEN (threshold), OPEN -> HALF_OPEN (recovery timeout + lock),
# HALF_OPEN -> CLOSED (probe ok) / OPEN (probe failed). Only one process may
# run the HALF_OPEN probe at a time, so five workers can't all hammer a dead
# service simultaneously.

_ALLOW_LUA = r"""
local key = KEYS[1]
local lock = KEYS[2]
local now = tonumber(ARGV[1])
local recovery = tonumber(ARGV[2])
local lock_ttl = tonumber(ARGV[3])
local owner = ARGV[4]
local ttl = tonumber(ARGV[5])

local raw = redis.call('GET', key)
if not raw then
    redis.call('SET', key, cjson.encode({
        state = 'closed', failures = 0, successes = 0,
        opened_at_ms = 0, last_failure_ms = 0, open_count = 0, probe_owner = ''
    }), 'EX', ttl)
    return 1
end
local s = cjson.decode(raw)

if s.state == 'closed' then
    return 1
end

if s.state == 'open' then
    if now - s.opened_at_ms < recovery then
        return 0
    end
    -- Recovery window passed: atomically become the single half-open prober.
    local ok = redis.call('SET', lock, owner, 'NX', 'PX', lock_ttl)
    if not ok then
        return 0
    end
    s.state = 'half_open'
    s.probe_owner = owner
    s.opened_at_ms = 0
    redis.call('SET', key, cjson.encode(s), 'EX', ttl)
    return 1
end

-- half_open: only the lock holder may probe; the lock also expires so a dead
-- worker's probe never blocks recovery forever.
local v = redis.call('GET', lock)
if v and v == owner then
    return 1
end
local ok = redis.call('SET', lock, owner, 'NX', 'PX', lock_ttl)
if not ok then
    return 0
end
s.probe_owner = owner
redis.call('SET', key, cjson.encode(s), 'EX', ttl)
return 1
"""

_FAILURE_LUA = r"""
local key = KEYS[1]
local lock = KEYS[2]
local now = tonumber(ARGV[1])
local threshold = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])

local raw = redis.call('GET', key)
if not raw then
    local s = {state = 'closed', failures = 1, successes = 0,
               opened_at_ms = 0, last_failure_ms = now, open_count = 0, probe_owner = ''}
    if threshold <= 1 then
        s.state = 'open'
        s.opened_at_ms = now
        s.open_count = 1
    end
    redis.call('SET', key, cjson.encode(s), 'EX', ttl)
    return 1
end

local s = cjson.decode(raw)
s.failures = (s.failures or 0) + 1
s.last_failure_ms = now

if s.state == 'closed' then
    if s.failures >= threshold then
        s.state = 'open'
        s.opened_at_ms = now
        s.open_count = (s.open_count or 0) + 1
        redis.call('DEL', lock)
    end
elseif s.state == 'half_open' then
    -- Probe failed: re-open and free the probe lock for the next recovery.
    s.state = 'open'
    s.opened_at_ms = now
    s.open_count = (s.open_count or 0) + 1
    s.probe_owner = ''
    redis.call('DEL', lock)
else
    -- already open: just refresh the failure time / TTL
end
redis.call('SET', key, cjson.encode(s), 'EX', ttl)
return 1
"""

_SUCCESS_LUA = r"""
local key = KEYS[1]
local lock = KEYS[2]
local now = tonumber(ARGV[1])
local threshold = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])

local raw = redis.call('GET', key)
if not raw then
    redis.call('SET', key, cjson.encode({
        state = 'closed', failures = 0, successes = 1,
        opened_at_ms = 0, last_failure_ms = 0, open_count = 0, probe_owner = ''
    }), 'EX', ttl)
    return 1
end

local s = cjson.decode(raw)
s.successes = (s.successes or 0) + 1

if s.state == 'half_open' then
    -- Probe succeeded: service is healthy again, close the breaker.
    s.state = 'closed'
    s.failures = 0
    s.opened_at_ms = 0
    s.probe_owner = ''
    redis.call('DEL', lock)
elseif s.state == 'closed' then
    -- Rolling window: a clean streak of `threshold` successes clears failures.
    if s.successes % threshold == 0 then
        s.failures = 0
    end
end
redis.call('SET', key, cjson.encode(s), 'EX', ttl)
return 1
"""


class CircuitBreaker:
    """Local (in-process) circuit breaker.

    This is the fallback used when Redis is unavailable or disabled, and the
    unit-testable building block. The registry swaps in a Redis-backed
    implementation automatically when Redis is reachable.
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
                "last_failure": None,
                "backend": "local",
            }


class RedisCircuitBreaker:
    """Distributed circuit breaker backed by Redis (sprint 3.5.1).

    Same public API as :class:`CircuitBreaker` (so callers don't care), but
    the state — including the failure/success counters, the OPEN timestamp
    and the HALF_OPEN probe lock — lives in Redis and is shared by every
    worker process.

    If Redis becomes unavailable the breaker transparently falls back to a
    local :class:`CircuitBreaker` so the platform keeps working.
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

        self._owner = f"{_hostname()}:{id(self):x}-{uuid.uuid4().hex[:8]}"
        self._prefix = settings.breaker_redis_prefix.rstrip(":")
        self._key = f"{self._prefix}:{name}"
        self._lock_key = f"{self._prefix}:{name}:probe"
        self._ttl = max(60, int(settings.breaker_state_ttl_seconds))
        self._probe_lock_ttl_ms = max(
            100, int(settings.breaker_probe_lock_ttl_seconds * 1000)
        )
        self._fallback = CircuitBreaker(
            name,
            failure_threshold=self.failure_threshold,
            recovery_timeout=self.recovery_timeout,
            half_open_max_calls=self.half_open_max_calls,
        )
        self._scripts: dict[str, Any] = {}

    # --- Redis plumbing ----------------------------------------------------

    def _client(self):
        from app.core.redis import redis_client

        return redis_client.raw_client

    def _script(self, client, source: str):
        cached = self._scripts.get(source)
        if cached is None:
            cached = client.register_script(source)
            self._scripts[source] = cached
        return cached

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    def _call(self, source: str, *args):
        client = self._client()
        if client is None:
            return None
        try:
            script = self._script(client, source)
            return script(
                keys=[self._key, self._lock_key],
                args=args,
                client=client,
            )
        except Exception:
            return None

    # --- API ---------------------------------------------------------------

    @property
    def state(self) -> BreakerState:
        return self._parse_state(self.snapshot())

    def allow_request(self) -> bool:
        result = self._call(
            _ALLOW_LUA,
            self._now_ms(),
            int(self.recovery_timeout * 1000),
            self._probe_lock_ttl_ms,
            self._owner,
            self._ttl,
        )
        if result is None:
            return self._fallback.allow_request()
        return bool(result)

    def record_success(self) -> None:
        result = self._call(
            _SUCCESS_LUA, self._now_ms(), self.failure_threshold, self._ttl
        )
        if result is None:
            self._fallback.record_success()

    def record_failure(self) -> None:
        result = self._call(
            _FAILURE_LUA, self._now_ms(), self.failure_threshold, self._ttl
        )
        if result is None:
            self._fallback.record_failure()

    def reset(self) -> None:
        client = self._client()
        if client is None:
            self._fallback.reset()
            return
        try:
            client.delete(self._key, self._lock_key)
            self._fallback.reset()
        except Exception:
            self._fallback.reset()

    def snapshot(self) -> dict[str, Any]:
        client = self._client()
        if client is None:
            return self._fallback.snapshot()
        try:
            raw = client.get(self._key)
        except Exception:
            return self._fallback.snapshot()
        if not raw:
            return self._closed_snapshot()
        import json

        try:
            s = json.loads(raw)
        except Exception:
            return self._closed_snapshot()
        return {
            "name": self.name,
            "state": s.get("state", "closed"),
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_seconds": round(self.recovery_timeout, 2),
            "failures": int(s.get("failures", 0)),
            "successes": int(s.get("successes", 0)),
            "open_count": int(s.get("open_count", 0)),
            "opened_at": _iso_ms(s.get("opened_at_ms")),
            "last_failure": _iso_ms(s.get("last_failure_ms")),
            "backend": "redis",
        }

    def _closed_snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": "closed",
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_seconds": round(self.recovery_timeout, 2),
            "failures": 0,
            "successes": 0,
            "open_count": 0,
            "opened_at": None,
            "last_failure": None,
            "backend": "redis",
        }

    @staticmethod
    def _parse_state(snapshot: dict[str, Any]) -> BreakerState:
        return BreakerState(snapshot.get("state", "closed"))


class _BreakerRegistry:
    """Named breakers shared process-wide (ollama / rossko / smtp / http)."""

    def __init__(self) -> None:
        self._breakers: dict[str, Any] = {}
        self._lock = threading.RLock()

    def get(self, name: str) -> Any:
        with self._lock:
            breaker = self._breakers.get(name)
            if breaker is None:
                params = _breaker_params(name)
                if _redis_enabled():
                    breaker = RedisCircuitBreaker(name, **params)
                else:
                    breaker = CircuitBreaker(name, **params)
                self._breakers[name] = breaker
            return breaker

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._breakers)

    def snapshots(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self.get(n).snapshot() for n in BREAKER_NAMES]

    def snapshot_map(self) -> dict[str, dict[str, Any]]:
        """One aggregated view: {name: {state, failures, ...}} for every breaker.

        Keys are stable (the BREAKER_NAMES set), so dashboards/alerts can rely
        on a fixed shape: {"ollama": {"state": "closed", "failures": 0}, ...}.
        """
        with self._lock:
            return {n: self.get(n).snapshot() for n in BREAKER_NAMES}


breaker_registry = _BreakerRegistry()


def get_breaker(name: str) -> Any:
    return breaker_registry.get(name)


def _breaker_params(name: str) -> dict[str, Any]:
    override = dict(settings.circuit_breaker_overrides.get(name) or {})
    return {
        "failure_threshold": override.get(
            "failure_threshold", settings.circuit_breaker_failure_threshold
        ),
        "recovery_timeout": override.get(
            "recovery_timeout", settings.circuit_breaker_recovery_timeout
        ),
        "half_open_max_calls": override.get(
            "half_open_max_calls", settings.circuit_breaker_half_open_max_calls
        ),
    }


def _redis_enabled() -> bool:
    from app.core.redis import redis_client

    return redis_client.available


def _iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _iso_ms(timestamp_ms: Any) -> str | None:
    if not timestamp_ms:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(int(timestamp_ms) / 1000, timezone.utc).isoformat()


def _wall_clock() -> float:
    """Wall-clock seconds (epoch) — for ``opened_at`` in snapshots.

    ``time.monotonic()`` must not be converted to a datetime (it is offset
    from boot, not from the epoch); store both internally.
    """
    return time.time()


def _hostname() -> str:
    import socket

    return socket.gethostname() or "worker"

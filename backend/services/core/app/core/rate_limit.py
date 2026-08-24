from __future__ import annotations

import threading
import time
from typing import Any

from app.core.redis import RedisClient, redis_client

_INCR_EXPIRE = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


class RateLimiter:
    """Fixed-window rate limiter with a Redis-backed store and an in-memory
    fallback (used in tests / when Redis is down).

    ``hit(key, limit, window_seconds)`` returns True while the call is allowed
    and False once the window budget is exhausted.
    """

    def __init__(self, redis: RedisClient = redis_client) -> None:
        self._redis = redis
        self._local: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()
        self._script: Any = None

    def _redis_hit(self, key: str, limit: int, window_seconds: int) -> bool | None:
        client = self._redis.raw_client
        if client is None:
            return None
        try:
            if self._script is None:
                self._script = client.register_script(_INCR_EXPIRE)
            count = int(self._script(keys=[key], args=[window_seconds]))
            return count <= limit
        except Exception:
            return None

    def _local_hit(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            start, count = self._local.get(key, (0.0, 0))
            if now - start >= window_seconds:
                start, count = now, 0
            count += 1
            self._local[key] = (start, count)
            return count <= limit

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        if self._redis.available:
            allowed = self._redis_hit(key, limit, window_seconds)
            if allowed is not None:
                return allowed
        return self._local_hit(key, limit, window_seconds)

    def count(self, key: str) -> int:
        if self._redis.available:
            raw = self._redis.get_json(key)
            return int(raw) if raw not in (None, "", 0, "0") else 0
        with self._lock:
            start, count = self._local.get(key, (0.0, 0))
            if time.monotonic() - start >= 0:
                return count
            return 0

    def retry_after_seconds(self, key: str, window_seconds: int) -> int:
        """Seconds until the current window resets (>= 1)."""

        if self._redis.available:
            ttl = self._redis.ttl(key)
            if ttl is not None:
                return max(1, ttl)
        with self._lock:
            start, _ = self._local.get(key, (0.0, 0))
            remaining = window_seconds - int(time.monotonic() - start)
            return max(1, remaining)

    def clear(self, key: str) -> None:
        if self._redis.available:
            self._redis.delete(key)
        with self._lock:
            self._local.pop(key, None)

    def set(self, key: str, value: int, ttl_seconds: int) -> None:
        if self._redis.available:
            self._redis.set_json(key, value, ttl_seconds=ttl_seconds)
        with self._lock:
            self._local[key] = (time.monotonic() + ttl_seconds, value)

    def get(self, key: str) -> int | None:
        if self._redis.available:
            raw = self._redis.get_json(key)
            return int(raw) if raw not in (None, "", 0, "0") else None
        with self._lock:
            entry = self._local.get(key)
            if entry is None:
                return None
            start, value = entry
            if time.monotonic() >= start:
                self._local.pop(key, None)
                return None
            return value


class LoginThrottle:
    """Brute-force protection for the login endpoint.

    State lives in Redis (``agentos:auth:*``) so every core instance shares the
    same view: a per-IP request budget plus a per-account failure counter that
    atomically locks the account once N failures accumulate inside the lock
    window. An in-memory fallback exists only for tests / when Redis is down;
    it is process-local and never used when Redis is reachable.
    """

    _IP_KEY = "agentos:auth:ip:{ip}"
    _FAIL_KEY = "agentos:auth:user:{email}"
    _LOCK_KEY = "agentos:auth:lock:{email}"

    # Atomically increment the failure counter (TTL set on first hit), and when
    # the threshold is crossed set the lock key with the lock TTL. Returns
    # {failures, locked}.
    _FAIL_SCRIPT = """
    local fails = redis.call('INCR', KEYS[1])
    if fails == 1 then
        redis.call('EXPIRE', KEYS[1], ARGV[1])
    end
    local locked = 0
    if fails >= tonumber(ARGV[2]) then
        redis.call('SET', KEYS[2], 1, 'EX', ARGV[1])
        locked = 1
    end
    return {fails, locked}
    """

    def __init__(self, limiter: RateLimiter | None = None) -> None:
        self.limiter = limiter or RateLimiter()
        from app.core.config import settings

        self._s = settings
        self._fail_script = None

    @staticmethod
    def _ip_key(ip: str) -> str:
        return LoginThrottle._IP_KEY.format(ip=ip)

    @staticmethod
    def _fail_key(email: str) -> str:
        return LoginThrottle._FAIL_KEY.format(email=email.lower())

    @staticmethod
    def _lock_key(email: str) -> str:
        return LoginThrottle._LOCK_KEY.format(email=email.lower())

    def request_allowed(self, ip: str) -> bool:
        """Per-IP attempt budget inside the rate window (atomic INCR+EXPIRE)."""
        return self.limiter.hit(
            self._ip_key(ip),
            self._s.login_rate_per_minute,
            self._s.login_rate_window_seconds,
        )

    def is_locked(self, email: str) -> bool:
        """True when the account is currently locked out (lock key exists)."""
        return self.limiter.get(self._lock_key(email)) is not None

    def record_failure(self, email: str) -> None:
        """Atomically count a failed attempt and lock the account on threshold.

        All replicas see the same counter because the increment and the lock
        decision happen in one Redis script.
        """
        fail_key = self._fail_key(email)
        lock_key = self._lock_key(email)
        client = self.limiter._redis.raw_client
        if client is not None:
            try:
                if self._fail_script is None:
                    self._fail_script = client.register_script(self._FAIL_SCRIPT)
                _fails, _locked = self._fail_script(
                    keys=[fail_key, lock_key],
                    args=[self._s.login_lock_seconds, self._s.login_failures_before_lock],
                )
                return
            except Exception:
                pass  # fall through to the local approximation
        # Local fallback (Redis down / tests): count in-process, same semantics.
        self.limiter.hit(
            fail_key, self._s.login_failures_before_lock, self._s.login_lock_seconds
        )
        if self.limiter.count(fail_key) >= self._s.login_failures_before_lock:
            self.limiter.set(lock_key, 1, ttl_seconds=self._s.login_lock_seconds)

    def record_success(self, email: str) -> None:
        """Reset the failure counter and any lock after a successful login."""
        self.limiter.clear(self._fail_key(email))
        self.limiter.clear(self._lock_key(email))

    def clear_state_for_test(self) -> None:
        """Reset all in-memory throttle state (test isolation helper)."""
        self.limiter._local.clear()

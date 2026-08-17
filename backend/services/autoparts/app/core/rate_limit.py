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

    Per-IP request budget plus a per-account failure counter that locks the
    account out once N failures accumulate inside the lock window.
    """

    def __init__(self, limiter: RateLimiter | None = None) -> None:
        self.limiter = limiter or RateLimiter()
        from app.core.config import settings

        self._s = settings

    @staticmethod
    def _fail_key(email: str) -> str:
        return f"rate:login:fail:{email.lower()}"

    @staticmethod
    def _lock_key(email: str) -> str:
        return f"rate:login:lock:{email.lower()}"

    def request_allowed(self, ip: str) -> bool:
        return self.limiter.hit(
            f"rate:login:ip:{ip}",
            self._s.login_rate_per_minute,
            self._s.login_rate_window_seconds,
        )

    def is_locked(self, email: str) -> bool:
        return self.limiter.get(self._lock_key(email)) is not None

    def record_failure(self, email: str) -> None:
        key = self._fail_key(email)
        # Each failure is one hit inside the lock window. Once the budget is
        # exhausted the account is locked out.
        allowed = self.limiter.hit(
            key, self._s.login_failures_before_lock, self._s.login_lock_seconds
        )
        if not allowed or self.limiter.count(key) >= self._s.login_failures_before_lock:
            self.limiter.set(
                self._lock_key(email), 1, ttl_seconds=self._s.login_lock_seconds
            )

    def record_success(self, email: str) -> None:
        self.limiter.clear(self._fail_key(email))
        self.limiter.clear(self._lock_key(email))

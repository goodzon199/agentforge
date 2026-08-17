from __future__ import annotations

import contextlib
import json
from typing import Any

from app.core.config import settings

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover - redis is optional for local dev
    redis_lib = None  # type: ignore[assignment]


class RedisClient:
    """Thin wrapper over redis-py. Degrades gracefully when unavailable."""

    def __init__(self, url: str, enabled: bool) -> None:
        self._url = url
        self._enabled = enabled and redis_lib is not None
        self._client = (
            redis_lib.Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=2.0,
                socket_timeout=5.0,
            )
            if self._enabled
            else None
        )

    @property
    def raw_client(self):
        """The underlying redis-py client (None when disabled)."""
        return self._client

    @property
    def available(self) -> bool:
        """Live availability check: Redis is only usable if it answers a ping."""
        if not self._enabled or self._client is None:
            return False
        try:
            return bool(self._client.ping())  # type: ignore[union-attr]
        except Exception:
            return False

    def ping(self) -> bool:
        return self.available

    def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        if not self.available:
            return
        with contextlib.suppress(Exception):
            self._client.set(key, json.dumps(value, default=str), ex=ttl_seconds)  # type: ignore[union-attr]

    def get_json(self, key: str) -> Any | None:
        if not self.available:
            return None
        try:
            raw = self._client.get(key)  # type: ignore[union-attr]
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def delete(self, key: str) -> None:
        if not self.available:
            return
        with contextlib.suppress(Exception):
            self._client.delete(key)  # type: ignore[union-attr]

    def ttl(self, key: str) -> int | None:
        """Seconds until ``key`` expires (None when missing / Redis down)."""
        if not self.available:
            return None
        try:
            ttl = self._client.ttl(key)  # type: ignore[union-attr]
            return ttl if isinstance(ttl, int) and ttl > 0 else None
        except Exception:
            return None

    def push(self, key: str, value: Any) -> None:
        """Push a message onto a list (used as a lightweight task queue)."""
        if not self.available:
            return
        with contextlib.suppress(Exception):
            self._client.rpush(key, json.dumps(value, default=str))  # type: ignore[union-attr]

    def pop(self, key: str, timeout: int = 1) -> Any | None:
        if not self.available:
            return None
        try:
            _, raw = self._client.blpop(key, timeout=timeout)  # type: ignore[union-attr]
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def push_raw(self, key: str, raw_value: str) -> None:
        """Push an already-JSON-encoded string onto a list unchanged."""
        if not self.available:
            return
        with contextlib.suppress(Exception):
            self._client.rpush(key, raw_value)  # type: ignore[union-attr]


redis_client = RedisClient(settings.redis_url, settings.redis_enabled)

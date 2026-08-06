from __future__ import annotations

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
            redis_lib.Redis.from_url(url, decode_responses=True) if self._enabled else None
        )

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
        try:
            self._client.set(key, json.dumps(value, default=str), ex=ttl_seconds)  # type: ignore[union-attr]
        except Exception:
            pass

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
        try:
            self._client.delete(key)  # type: ignore[union-attr]
        except Exception:
            pass

    def push(self, key: str, value: Any) -> None:
        """Push a message onto a list (used as a lightweight task queue)."""
        if not self.available:
            return
        try:
            self._client.rpush(key, json.dumps(value, default=str))  # type: ignore[union-attr]
        except Exception:
            pass

    def pop(self, key: str, timeout: int = 1) -> Any | None:
        if not self.available:
            return None
        try:
            _, raw = self._client.blpop(key, timeout=timeout)  # type: ignore[union-attr]
            return json.loads(raw) if raw else None
        except Exception:
            return None


redis_client = RedisClient(settings.redis_url, settings.redis_enabled)

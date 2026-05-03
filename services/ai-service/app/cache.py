from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from app.config import Settings

try:
    import redis
    from redis import Redis
    from redis.exceptions import RedisError
except Exception:  # pragma: no cover - import path differs between environments
    redis = None  # type: ignore[assignment]
    Redis = Any  # type: ignore[misc,assignment]

    class RedisError(Exception):
        pass


logger = logging.getLogger(__name__)


class CacheClient:
    def get_json(self, key: str) -> Any | None:
        raise NotImplementedError

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        raise NotImplementedError

    def get_text(self, key: str) -> str | None:
        raise NotImplementedError

    def set_text(self, key: str, value: str, ttl_seconds: int) -> None:
        raise NotImplementedError

    def set_if_absent_text(self, key: str, value: str, ttl_seconds: int) -> bool:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def delete_prefix(self, prefix: str) -> None:
        raise NotImplementedError

    def get(self, key: str) -> Any | None:
        return self.get_json(key)

    def set(self, key: str, value: Any, expire: int = 60) -> None:
        self.set_json(key, value, expire)


class InMemoryCache(CacheClient):
    def __init__(self, prefix: str = "ai:") -> None:
        self._prefix = prefix
        self._items: dict[str, tuple[float | None, str]] = {}
        self._lock = threading.Lock()

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [k for k, (exp, _) in self._items.items() if exp is not None and exp <= now]
        for key in expired:
            self._items.pop(key, None)

    def get_json(self, key: str) -> Any | None:
        text = self.get_text(key)
        if text is None:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        self.set_text(key, json.dumps(value, separators=(",", ":"), ensure_ascii=False), ttl_seconds)

    def get_text(self, key: str) -> str | None:
        with self._lock:
            self._purge_expired()
            item = self._items.get(self._key(key))
            if not item:
                return None
            return item[1]

    def set_text(self, key: str, value: str, ttl_seconds: int) -> None:
        expires_at = time.time() + ttl_seconds if ttl_seconds > 0 else None
        with self._lock:
            self._purge_expired()
            self._items[self._key(key)] = (expires_at, value)

    def set_if_absent_text(self, key: str, value: str, ttl_seconds: int) -> bool:
        expires_at = time.time() + ttl_seconds if ttl_seconds > 0 else None
        with self._lock:
            self._purge_expired()
            full_key = self._key(key)
            if full_key in self._items:
                return False
            self._items[full_key] = (expires_at, value)
            return True

    def delete(self, key: str) -> None:
        with self._lock:
            self._items.pop(self._key(key), None)

    def delete_prefix(self, prefix: str) -> None:
        full_prefix = self._key(prefix)
        with self._lock:
            keys = [key for key in self._items.keys() if key.startswith(full_prefix)]
            for key in keys:
                self._items.pop(key, None)


class RedisCache(CacheClient):
    def __init__(self, client: Redis, prefix: str = "ai:") -> None:
        self._client = client
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get_json(self, key: str) -> Any | None:
        raw = self.get_text(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        self.set_text(key, payload, ttl_seconds)

    def get_text(self, key: str) -> str | None:
        value = self._client.get(self._key(key))
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return value

    def set_text(self, key: str, value: str, ttl_seconds: int) -> None:
        ttl = max(ttl_seconds, 1)
        self._client.set(self._key(key), value, ex=ttl)

    def set_if_absent_text(self, key: str, value: str, ttl_seconds: int) -> bool:
        ttl = max(ttl_seconds, 1)
        return bool(self._client.set(self._key(key), value, ex=ttl, nx=True))

    def delete(self, key: str) -> None:
        self._client.delete(self._key(key))

    def delete_prefix(self, prefix: str) -> None:
        pattern = self._key(f"{prefix}*")
        cursor = 0
        while True:
            cursor, keys = self._client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                self._client.delete(*keys)
            if cursor == 0:
                break


def build_cache(settings: Settings) -> CacheClient:
    prefix = settings.redis_prefix
    if not settings.redis_enabled:
        logger.info("Redis cache disabled by config; using in-memory cache.")
        return InMemoryCache(prefix=prefix)

    if redis is None:
        logger.warning("Redis package not installed; using in-memory cache.")
        return InMemoryCache(prefix=prefix)

    try:
        client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()
        logger.info("Redis cache connected: %s", settings.redis_url)
        return RedisCache(client, prefix=prefix)
    except RedisError as exc:
        logger.warning("Redis unavailable (%s); using in-memory cache.", exc)
        return InMemoryCache(prefix=prefix)

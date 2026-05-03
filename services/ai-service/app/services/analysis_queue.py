from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from app.config import Settings

try:  # pragma: no cover - optional in certain environments
    import redis
    from redis import Redis
except Exception:  # pragma: no cover
    redis = None  # type: ignore[assignment]
    Redis = Any  # type: ignore[misc,assignment]


logger = logging.getLogger(__name__)


class AnalysisQueueService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._queue_key = f"{settings.redis_prefix}queue:requirement-analysis"
        self._running = False
        self._worker_thread: threading.Thread | None = None
        self._redis: Redis | None = None
        self._redis_failed = False
        self._local_queue: list[str] = []
        self._lock = threading.Lock()

        if settings.redis_enabled and redis is not None:
            self._redis = self._connect_redis()

    def _connect_redis(self) -> Redis | None:
        if redis is None:
            return None
        try:
            client = redis.Redis.from_url(
                self._settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            client.ping()
            self._redis_failed = False
            return client
        except Exception as exc:  # pragma: no cover - runtime infra issue
            logger.warning("analysis queue redis unavailable, fallback to in-memory: %s", exc)
            self._redis_failed = True
            return None

    def enqueue(self, operation_id: str) -> None:
        if self._redis is not None:
            try:
                self._redis.rpush(self._queue_key, operation_id)
                return
            except Exception as exc:
                logger.warning("analysis queue enqueue redis failed, fallback to memory: %s", exc)
                self._redis = None
                self._redis_failed = True
        with self._lock:
            self._local_queue.append(operation_id)

    def start_worker(self, handler: Any) -> None:
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            args=(handler,),
            daemon=True,
            name="requirement-analysis-worker",
        )
        self._worker_thread.start()

    def stop_worker(self) -> None:
        self._running = False
        thread = self._worker_thread
        if thread and thread.is_alive():
            thread.join(timeout=2)

    def _worker_loop(self, handler: Any) -> None:
        while self._running:
            operation_id = self._dequeue()
            if not operation_id:
                time.sleep(0.2)
                continue
            try:
                asyncio.run(handler.execute_operation(operation_id))
            except Exception as exc:  # pragma: no cover - runtime provider failure
                logger.exception("analysis worker failed operation_id=%s error=%s", operation_id, exc)

    def _dequeue(self) -> str | None:
        if self._redis is not None:
            try:
                result = self._redis.blpop(self._queue_key, timeout=1)
                if not result:
                    return None
                _key, value = result
                return value if isinstance(value, str) and value else None
            except TimeoutError:
                # Network jitter or Redis read timeout: keep worker alive and try again.
                return None
            except Exception as exc:
                logger.warning("analysis queue dequeue redis failed, fallback to memory: %s", exc)
                self._redis = None
                self._redis_failed = True
                return None

        if self._settings.redis_enabled and redis is not None and self._redis_failed:
            self._redis = self._connect_redis()

        with self._lock:
            if not self._local_queue:
                return None
            return self._local_queue.pop(0)

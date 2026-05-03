from __future__ import annotations

import time
import logging
from typing import Any
from app.cache import CacheClient

logger = logging.getLogger(__name__)

class LockService:
    def __init__(self, cache: CacheClient):
        self._cache = cache
        self._lock_prefix = "lock:"

    def _key(self, resource_type: str, resource_id: str) -> str:
        return f"{self._lock_prefix}{resource_type}:{resource_id}"

    def acquire_lock(
        self, 
        resource_type: str, 
        resource_id: str, 
        owner_id: str, 
        owner_name: str,
        ttl_seconds: int = 60
    ) -> dict[str, Any] | None:
        """
        Attempts to acquire a lock for a resource.
        Returns the lock info if successful, or the current lock info if failed (someone else has it).
        If the current user already has the lock, it refreshes it.
        """
        key = self._key(resource_type, resource_id)
        now = time.time()
        
        lock_info = {
            "ownerId": owner_id,
            "ownerName": owner_name,
            "acquiredAt": now,
            "expiresAt": now + ttl_seconds
        }
        
        # Check if already locked
        current_lock = self._cache.get_json(key)
        if current_lock:
            if current_lock.get("ownerId") == owner_id:
                # Refresh lock
                self._cache.set_json(key, lock_info, ttl_seconds)
                return lock_info
            else:
                # Someone else has it
                return current_lock
                
        # Try to set
        success = self._cache.set_if_absent_text(
            key, 
            self._to_json(lock_info), 
            ttl_seconds
        )
        if success:
            return lock_info
        
        # Race condition: someone else got it between get and set_if_absent
        return self._cache.get_json(key)

    def release_lock(self, resource_type: str, resource_id: str, owner_id: str) -> bool:
        """
        Releases a lock if the owner matches.
        """
        key = self._key(resource_type, resource_id)
        current_lock = self._cache.get_json(key)
        if not current_lock:
            return True
            
        if current_lock.get("ownerId") == owner_id:
            self._cache.delete(key)
            return True
        
        return False

    def get_lock_info(self, resource_type: str, resource_id: str) -> dict[str, Any] | None:
        return self._cache.get_json(self._key(resource_type, resource_id))

    def _to_json(self, data: Any) -> str:
        import json
        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)

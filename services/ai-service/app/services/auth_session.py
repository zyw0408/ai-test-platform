from __future__ import annotations

from typing import Any

from app.cache import CacheClient


class AuthSessionService:
    def __init__(self, cache: CacheClient) -> None:
        self._cache = cache

    @staticmethod
    def _token_key(token_id: str) -> str:
        return f"auth:token:{token_id}"

    @staticmethod
    def _user_key(user_id: str) -> str:
        return f"auth:user:{user_id}"

    def store_token_session(
        self,
        *,
        token_id: str,
        user_id: str,
        username: str,
        role: str,
        ttl_seconds: int,
    ) -> None:
        self._cache.set_json(
            self._token_key(token_id),
            {
                "userId": user_id,
                "username": username,
                "role": role,
            },
            ttl_seconds,
        )

    def is_token_active(self, token_id: str, user_id: str) -> bool:
        payload = self._cache.get_json(self._token_key(token_id))
        if not isinstance(payload, dict):
            return False
        return payload.get("userId") == user_id

    def revoke_token(self, token_id: str) -> None:
        self._cache.delete(self._token_key(token_id))

    def cache_user(self, user: dict[str, Any], ttl_seconds: int = 120) -> None:
        user_id = user.get("id")
        if not isinstance(user_id, str) or not user_id:
            return
        self._cache.set_json(self._user_key(user_id), user, ttl_seconds)

    def get_cached_user(self, user_id: str) -> dict[str, Any] | None:
        value = self._cache.get_json(self._user_key(user_id))
        if not isinstance(value, dict):
            return None
        return value

    def evict_user(self, user_id: str) -> None:
        self._cache.delete(self._user_key(user_id))

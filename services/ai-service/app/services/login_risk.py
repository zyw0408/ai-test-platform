from __future__ import annotations

import hashlib
import hmac
import time

from app.cache import CacheClient
from app.config import Settings


class LoginRiskBlockedError(ValueError):
    def __init__(self, message: str, *, seconds_left: int) -> None:
        super().__init__(message)
        self.seconds_left = max(seconds_left, 1)


class LoginRiskService:
    def __init__(self, cache: CacheClient, settings: Settings) -> None:
        self._cache = cache
        self._fail_limit = max(settings.login_fail_limit, 2)
        self._window_seconds = max(settings.login_fail_window_seconds, 60)
        self._lock_seconds = max(settings.login_lock_seconds, 60)
        self._secret = settings.privacy_hash_secret.encode("utf-8")

    def ensure_allowed(
        self,
        *,
        method: str,
        account: str | None,
        ip: str | None,
    ) -> None:
        now = int(time.time())
        keys = self._lock_keys(method=method, account=account, ip=ip)
        for scope, key in keys:
            payload = self._cache.get_json(key)
            if not isinstance(payload, dict):
                continue
            locked_until = payload.get("lockedUntil")
            if not isinstance(locked_until, int):
                continue
            if locked_until <= now:
                self._cache.delete(key)
                continue
            seconds_left = locked_until - now
            raise LoginRiskBlockedError(
                f"{scope} 登录失败次数过多，请稍后重试",
                seconds_left=seconds_left,
            )

    def register_failure(
        self,
        *,
        method: str,
        account: str | None,
        ip: str | None,
    ) -> None:
        now = int(time.time())
        for _, key in self._counter_keys(method=method, account=account, ip=ip):
            count = self._increment_counter(key, now=now)
            if count >= self._fail_limit:
                self._cache.set_json(
                    self._lock_key_from_counter(key),
                    {"lockedUntil": now + self._lock_seconds},
                    self._lock_seconds,
                )

    def clear_on_success(
        self,
        *,
        method: str,
        account: str | None,
        ip: str | None,
    ) -> None:
        for _, key in self._counter_keys(method=method, account=account, ip=ip):
            self._cache.delete(key)
            self._cache.delete(self._lock_key_from_counter(key))

    def unlock(
        self,
        *,
        method: str,
        account: str | None = None,
        ip: str | None = None,
    ) -> None:
        if not account and not ip:
            raise ValueError("account 和 ip 至少提供一个")
        for _, key in self._counter_keys(method=method, account=account, ip=ip):
            self._cache.delete(key)
            self._cache.delete(self._lock_key_from_counter(key))

    def _increment_counter(self, key: str, *, now: int) -> int:
        payload = self._cache.get_json(key)
        if isinstance(payload, dict):
            count = int(payload.get("count", 0)) + 1
        else:
            count = 1
        self._cache.set_json(
            key,
            {"count": count, "updatedAt": now},
            self._window_seconds,
        )
        return count

    def _counter_keys(
        self,
        *,
        method: str,
        account: str | None,
        ip: str | None,
    ) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        if account and account.strip():
            account_digest = self._digest(account.strip().lower())
            items.append(("账号", f"auth:risk:counter:account:{method}:{account_digest}"))
        if ip and ip.strip():
            ip_digest = self._digest(ip.strip())
            items.append(("IP", f"auth:risk:counter:ip:{method}:{ip_digest}"))
        return items

    def _lock_keys(
        self,
        *,
        method: str,
        account: str | None,
        ip: str | None,
    ) -> list[tuple[str, str]]:
        return [(scope, self._lock_key_from_counter(counter_key)) for scope, counter_key in self._counter_keys(method=method, account=account, ip=ip)]

    @staticmethod
    def _lock_key_from_counter(counter_key: str) -> str:
        return counter_key.replace(":counter:", ":lock:")

    def _digest(self, raw: str) -> str:
        return hmac.new(self._secret, raw.encode("utf-8"), hashlib.sha256).hexdigest()

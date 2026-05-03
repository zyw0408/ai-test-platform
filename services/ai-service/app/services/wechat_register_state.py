from __future__ import annotations

import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

from app.cache import CacheClient
from app.config import Settings


class WechatRegisterStateError(ValueError):
    pass


class WechatRegisterStateService:
    def __init__(self, cache: CacheClient, settings: Settings) -> None:
        self._cache = cache
        self._settings = settings
        self._state_ttl_seconds = max(settings.wechat_register_state_ttl_seconds, 60)
        self._allowed_hosts = {host.strip().lower() for host in settings.wechat_oauth_allowed_redirect_hosts if host.strip()}
        self._allowed_next_prefixes = [
            prefix.strip()
            for prefix in settings.wechat_oauth_allowed_next_prefixes
            if prefix.strip().startswith("/")
        ]
        if not self._allowed_next_prefixes:
            self._allowed_next_prefixes = ["/"]

    @property
    def state_ttl_seconds(self) -> int:
        return self._state_ttl_seconds

    def issue_state(self, redirect_uri: str) -> str:
        next_path = self.validate_redirect_uri(redirect_uri)
        state = secrets.token_urlsafe(24)
        self._cache.set_json(
            self._state_key(state),
            {"redirectUri": redirect_uri, "nextPath": next_path},
            self._state_ttl_seconds,
        )
        return state

    def consume_state(
        self,
        *,
        state: str | None,
        code: str | None,
        next_path: str | None = None,
    ) -> None:
        normalized_state = (state or "").strip()
        normalized_code = (code or "").strip()
        if not normalized_state:
            raise WechatRegisterStateError("缺少微信 state")
        if len(normalized_state) < 16 or len(normalized_state) > 128:
            raise WechatRegisterStateError("微信 state 格式不合法")
        if not normalized_code:
            raise WechatRegisterStateError("缺少微信 code")

        payload = self._cache.get_json(self._state_key(normalized_state))
        if not isinstance(payload, dict):
            raise WechatRegisterStateError("微信 state 已失效，请重新发起授权")
        self._cache.delete(self._state_key(normalized_state))
        expected_next = payload.get("nextPath")
        expected_next_text = expected_next if isinstance(expected_next, str) and expected_next else None

        provided_next = self.normalize_next_path(next_path)
        if expected_next_text != provided_next:
            raise WechatRegisterStateError("微信回调 next 参数校验失败，请重新发起授权")

        code_digest = self._hash_code(normalized_code)
        if not self._cache.set_if_absent_text(
            self._code_replay_key(code_digest),
            "1",
            self._state_ttl_seconds,
        ):
            raise WechatRegisterStateError("微信授权码已被使用，请重新授权")

    def validate_redirect_uri(self, redirect_uri: str) -> str | None:
        uri = redirect_uri.strip()
        parsed = urlparse(uri)
        if parsed.scheme not in {"http", "https"}:
            raise WechatRegisterStateError("redirectUri 必须是 http/https 地址")
        if not parsed.netloc:
            raise WechatRegisterStateError("redirectUri 缺少主机名")
        host = (parsed.hostname or "").lower()
        if self._allowed_hosts and host not in self._allowed_hosts:
            raise WechatRegisterStateError("redirectUri 不在允许名单中")
        raw_next = parse_qs(parsed.query).get("next", [None])[0]
        return self.normalize_next_path(raw_next)

    def normalize_next_path(self, next_path: str | None) -> str | None:
        raw = (next_path or "").strip()
        if not raw:
            return None
        if not raw.startswith("/") or raw.startswith("//"):
            raise WechatRegisterStateError("next 参数必须是站内路径")
        parsed = urlparse(raw)
        if parsed.scheme or parsed.netloc:
            raise WechatRegisterStateError("next 参数必须是站内路径")

        path = parsed.path or "/"
        if not self._is_next_allowed(path):
            raise WechatRegisterStateError("next 参数不在允许范围内")

        normalized = path
        if parsed.query:
            normalized += f"?{parsed.query}"
        if parsed.fragment:
            normalized += f"#{parsed.fragment}"
        return normalized

    def _hash_code(self, code: str) -> str:
        seed = f"{self._settings.privacy_hash_secret}:{code}".encode("utf-8")
        return hashlib.sha256(seed).hexdigest()

    def _is_next_allowed(self, path: str) -> bool:
        for prefix in self._allowed_next_prefixes:
            if prefix == "/":
                if path == "/":
                    return True
                continue
            if path == prefix or path.startswith(f"{prefix}/"):
                return True
        return False

    @staticmethod
    def _state_key(state: str) -> str:
        return f"auth:register:wechat:state:{state}"

    @staticmethod
    def _code_replay_key(code_digest: str) -> str:
        return f"auth:register:wechat:code:{code_digest}"

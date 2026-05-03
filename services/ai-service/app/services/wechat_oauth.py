from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings


class WechatOAuthError(ValueError):
    pass


@dataclass(slots=True)
class WechatUserInfo:
    openid: str
    unionid: str | None = None
    nickname: str | None = None
    avatar_url: str | None = None


class WechatOAuthService:
    ACCESS_TOKEN_URL = "https://api.weixin.qq.com/sns/oauth2/access_token"
    USERINFO_URL = "https://api.weixin.qq.com/sns/userinfo"
    AUTHORIZE_URL = "https://open.weixin.qq.com/connect/oauth2/authorize"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_enabled(self) -> bool:
        return bool(
            self._settings.wechat_oauth_enabled
            and self._settings.wechat_app_id
            and self._settings.wechat_app_secret
        )

    def build_authorize_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        scope: str = "snsapi_userinfo",
    ) -> str:
        if not self.is_enabled():
            raise WechatOAuthError("微信 OAuth 未开启")
        normalized_scope = scope.strip() or "snsapi_userinfo"
        if normalized_scope not in {"snsapi_userinfo", "snsapi_base"}:
            raise WechatOAuthError("微信 scope 不合法")
        app_id = (self._settings.wechat_app_id or "").strip()
        if not app_id:
            raise WechatOAuthError("微信 appId 未配置")

        query = urlencode(
            {
                "appid": app_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": normalized_scope,
                "state": state,
            }
        )
        return f"{self.AUTHORIZE_URL}?{query}#wechat_redirect"

    async def exchange_code(self, code: str) -> WechatUserInfo:
        if not self.is_enabled():
            raise WechatOAuthError("微信 OAuth 未开启，请改用 openId 登录")
        normalized_code = code.strip()
        if not normalized_code:
            raise WechatOAuthError("微信 code 不能为空")

        token_payload = await self._request_json(
            self.ACCESS_TOKEN_URL,
            params={
                "appid": self._settings.wechat_app_id,
                "secret": self._settings.wechat_app_secret,
                "code": normalized_code,
                "grant_type": "authorization_code",
            },
        )
        self._raise_if_error(token_payload, stage="code 交换")

        openid = token_payload.get("openid")
        access_token = token_payload.get("access_token")
        if not isinstance(openid, str) or not openid:
            raise WechatOAuthError("微信 code 交换失败：缺少 openid")
        if not isinstance(access_token, str) or not access_token:
            raise WechatOAuthError("微信 code 交换失败：缺少 access_token")

        unionid = token_payload.get("unionid")
        if unionid is not None and not isinstance(unionid, str):
            unionid = None

        nickname: str | None = None
        avatar_url: str | None = None
        userinfo_payload = await self._request_json(
            self.USERINFO_URL,
            params={
                "access_token": access_token,
                "openid": openid,
                "lang": "zh_CN",
            },
        )
        if isinstance(userinfo_payload, dict) and "openid" in userinfo_payload:
            self._raise_if_error(userinfo_payload, stage="获取用户信息")
            nickname_raw = userinfo_payload.get("nickname")
            avatar_raw = userinfo_payload.get("headimgurl")
            nickname = nickname_raw if isinstance(nickname_raw, str) and nickname_raw.strip() else None
            avatar_url = avatar_raw if isinstance(avatar_raw, str) and avatar_raw.strip() else None

        return WechatUserInfo(
            openid=openid,
            unionid=unionid,
            nickname=nickname,
            avatar_url=avatar_url,
        )

    async def _request_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        timeout = httpx.Timeout(self._settings.wechat_http_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WechatOAuthError(f"微信接口请求失败: {exc}") from exc
        if not isinstance(payload, dict):
            raise WechatOAuthError("微信接口返回格式错误")
        return payload

    @staticmethod
    def _raise_if_error(payload: dict[str, Any], *, stage: str) -> None:
        errcode = payload.get("errcode")
        if errcode in (None, 0):
            return
        errmsg = payload.get("errmsg")
        detail = errmsg if isinstance(errmsg, str) and errmsg else "unknown"
        raise WechatOAuthError(f"微信 {stage}失败: {detail} ({errcode})")

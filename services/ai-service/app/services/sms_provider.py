from __future__ import annotations

import json
import logging
import re
from typing import Protocol

from app.config import Settings


logger = logging.getLogger(__name__)


class SmsProviderError(ValueError):
    pass


class SmsProvider(Protocol):
    @property
    def provider_name(self) -> str:
        ...

    def send_register_code(self, *, phone: str, code: str) -> None:
        ...


class MockSmsProvider:
    @property
    def provider_name(self) -> str:
        return "mock"

    def send_register_code(self, *, phone: str, code: str) -> None:
        logger.info("mock sms sent. phone=%s code=%s", phone, code)


class AliyunSmsProvider:
    def __init__(self, settings: Settings) -> None:
        self._access_key_id = (settings.sms_aliyun_access_key_id or "").strip()
        self._access_key_secret = (settings.sms_aliyun_access_key_secret or "").strip()
        self._sign_name = (settings.sms_aliyun_sign_name or "").strip()
        self._template_code = (settings.sms_aliyun_template_code or "").strip()
        self._template_param_key = settings.sms_aliyun_template_param_key.strip()
        self._endpoint = settings.sms_aliyun_endpoint.strip() or "dysmsapi.aliyuncs.com"

        missing = [
            key
            for key, value in {
                "AI_SERVICE_SMS_ALIYUN_ACCESS_KEY_ID": self._access_key_id,
                "AI_SERVICE_SMS_ALIYUN_ACCESS_KEY_SECRET": self._access_key_secret,
                "AI_SERVICE_SMS_ALIYUN_SIGN_NAME": self._sign_name,
                "AI_SERVICE_SMS_ALIYUN_TEMPLATE_CODE": self._template_code,
            }.items()
            if not value
        ]
        if missing:
            raise SmsProviderError(f"阿里云短信配置缺失: {', '.join(missing)}")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", self._template_param_key):
            raise SmsProviderError(
                "AI_SERVICE_SMS_ALIYUN_TEMPLATE_PARAM_KEY 不合法，应为字母/下划线开头且仅包含字母数字下划线"
            )

        try:
            from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
            from alibabacloud_tea_openapi import models as open_api_models
        except Exception as exc:  # pragma: no cover - dependency install checked at runtime
            raise SmsProviderError(
                "缺少阿里云短信 SDK，请安装依赖后重试 "
                "(alibabacloud-dysmsapi20170525, alibabacloud-tea-openapi)"
            ) from exc

        config = open_api_models.Config(
            access_key_id=self._access_key_id,
            access_key_secret=self._access_key_secret,
            endpoint=self._endpoint,
        )
        self._client = DysmsapiClient(config)

    @property
    def provider_name(self) -> str:
        return "aliyun"

    def send_register_code(self, *, phone: str, code: str) -> None:
        if not re.fullmatch(r"\d{4,8}", code):
            raise SmsProviderError("短信验证码格式不合法，应为 4-8 位数字")

        template_param = json.dumps(
            {self._template_param_key: code},
            ensure_ascii=False,
            separators=(",", ":"),
        )

        try:
            from alibabacloud_dysmsapi20170525 import models as dysms_models
        except Exception as exc:  # pragma: no cover
            raise SmsProviderError("阿里云短信 SDK 加载失败") from exc

        request = dysms_models.SendSmsRequest(
            sign_name=self._sign_name,
            template_code=self._template_code,
            phone_numbers=phone,
            template_param=template_param,
        )
        try:
            response = self._client.send_sms(request)
        except Exception as exc:  # pragma: no cover - network/provider failure
            raise SmsProviderError(f"阿里云短信发送失败: {exc}") from exc

        body = getattr(response, "body", None)
        provider_code = getattr(body, "code", None)
        provider_message = getattr(body, "message", None)
        if provider_code != "OK":
            raise SmsProviderError(
                f"阿里云短信返回异常: {provider_code or 'UNKNOWN'} {provider_message or ''}".strip()
            )


def build_sms_provider(settings: Settings) -> SmsProvider:
    provider = settings.sms_provider.strip().lower()
    if provider in {"", "mock", "none"}:
        logger.info("SMS provider: mock")
        return MockSmsProvider()
    if provider == "aliyun":
        logger.info("SMS provider: aliyun")
        return AliyunSmsProvider(settings)
    if provider == "tencent":
        raise SmsProviderError("当前仅实现了阿里云短信 provider，请先使用 aliyun 或 mock")
    raise SmsProviderError(f"不支持的短信 provider: {settings.sms_provider}")

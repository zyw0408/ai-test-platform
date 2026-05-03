from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from app.cache import CacheClient
from app.config import Settings
from app.privacy import PrivacyCrypto
from app.services.sms_provider import SmsProvider, SmsProviderError


class RegistrationRateLimitError(ValueError):
    def __init__(self, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RegistrationDeliveryError(ValueError):
    pass


class RegistrationService:
    def __init__(self, cache: CacheClient, settings: Settings, sms_provider: SmsProvider) -> None:
        self._cache = cache
        self._privacy = PrivacyCrypto(settings.privacy_hash_secret, settings.privacy_fernet_key)
        self._sms_provider = sms_provider
        self._sms_code_ttl_seconds = max(settings.register_sms_code_ttl_seconds, 60)
        self._sms_cooldown_seconds = max(settings.register_sms_cooldown_seconds, 10)
        self._sms_daily_limit = max(settings.register_sms_daily_limit, 1)
        self._test_code = settings.sms_login_code.strip()
        self._sms_mode = "test" if self._test_code else "provider"

    def get_public_meta(self) -> dict[str, object]:
        return {
            "sms": {
                "mode": self._sms_mode,
                "provider": self._sms_provider.provider_name,
                "ttlSeconds": self._sms_code_ttl_seconds,
                "cooldownSeconds": self._sms_cooldown_seconds,
                "dailyLimit": self._sms_daily_limit,
                "testCode": self._test_code if self._sms_mode == "test" else None,
            }
        }

    def send_sms_code(self, phone: str) -> dict[str, int | str]:
        normalized = self._privacy.normalize_phone(phone)
        phone_digest = self._privacy.hash_phone(normalized)

        cooldown_key = self._cooldown_key(phone_digest)
        if self._cache.get_text(cooldown_key):
            raise RegistrationRateLimitError(
                "验证码发送过于频繁，请稍后再试",
                retry_after=self._sms_cooldown_seconds,
            )

        daily_key = self._daily_count_key(phone_digest)
        daily_count = self._read_int(self._cache.get_text(daily_key))
        if daily_count >= self._sms_daily_limit:
            raise RegistrationRateLimitError("今日验证码发送次数已达上限，请明天再试")

        code = self._generate_sms_code()
        if self._sms_mode != "test":
            try:
                self._sms_provider.send_register_code(phone=normalized, code=code)
            except SmsProviderError as exc:
                raise RegistrationDeliveryError(str(exc)) from exc

        code_key = self._sms_code_key(phone_digest)
        self._cache.set_json(
            code_key,
            {"code": code},
            self._sms_code_ttl_seconds,
        )
        self._cache.set_text(cooldown_key, "1", self._sms_cooldown_seconds)
        self._cache.set_text(
            daily_key,
            str(daily_count + 1),
            self._seconds_until_day_end(),
        )
        return {
            "phone": self._privacy.mask_phone(normalized) or "***",
            "ttlSeconds": self._sms_code_ttl_seconds,
            "cooldownSeconds": self._sms_cooldown_seconds,
        }

    def verify_sms_code(self, *, phone: str, code: str, consume: bool = True) -> bool:
        normalized = self._privacy.normalize_phone(phone)
        provided = code.strip()
        if not provided:
            return False

        # Keep a fixed test code for local/dev workflows.
        test_code = self._test_code
        if test_code and secrets.compare_digest(provided, test_code):
            return True

        phone_digest = self._privacy.hash_phone(normalized)
        payload = self._cache.get_json(self._sms_code_key(phone_digest))
        if not isinstance(payload, dict):
            return False
        expected = payload.get("code")
        if not isinstance(expected, str):
            return False
        ok = secrets.compare_digest(provided, expected)
        if ok and consume:
            self._cache.delete(self._sms_code_key(phone_digest))
        return ok

    @staticmethod
    def _read_int(value: str | None) -> int:
        if not value:
            return 0
        try:
            return int(value)
        except ValueError:
            return 0

    def _generate_sms_code(self) -> str:
        if self._test_code:
            return self._test_code
        return f"{secrets.randbelow(1_000_000):06d}"

    @staticmethod
    def _sms_code_key(phone_digest: str) -> str:
        return f"auth:register:sms:code:{phone_digest}"

    @staticmethod
    def _cooldown_key(phone_digest: str) -> str:
        return f"auth:register:sms:cooldown:{phone_digest}"

    def _daily_count_key(self, phone_digest: str) -> str:
        day_key = datetime.now().strftime("%Y%m%d")
        return f"auth:register:sms:daily:{phone_digest}:{day_key}"

    def _seconds_until_day_end(self) -> int:
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(int((tomorrow - now).total_seconds()), 60)

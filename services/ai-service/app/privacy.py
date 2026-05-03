from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re

from cryptography.fernet import Fernet, InvalidToken


class PrivacyCrypto:
    def __init__(self, hash_secret: str, encryption_key: str | None = None) -> None:
        if not hash_secret:
            raise ValueError("hash_secret 不能为空")
        self._hash_secret = hash_secret.encode("utf-8")
        self._fernet = Fernet(self._build_fernet_key(hash_secret, encryption_key))

    @staticmethod
    def normalize_phone(phone: str) -> str:
        raw = phone.strip()
        if raw.startswith("+"):
            return "+" + re.sub(r"\D", "", raw[1:])
        return re.sub(r"\D", "", raw)

    def hash_phone(self, phone: str) -> str:
        normalized = self.normalize_phone(phone)
        if not normalized:
            raise ValueError("手机号不能为空")
        return self._hash("phone", normalized)

    def hash_wechat_openid(self, openid: str) -> str:
        value = openid.strip()
        if not value:
            raise ValueError("微信 openid 不能为空")
        return self._hash("wechat_openid", value)

    def hash_wechat_unionid(self, unionid: str) -> str:
        value = unionid.strip()
        if not value:
            raise ValueError("微信 unionid 不能为空")
        return self._hash("wechat_unionid", value)

    def encrypt_text(self, value: str) -> str:
        raw = value.strip()
        if not raw:
            raise ValueError("加密内容不能为空")
        return self._fernet.encrypt(raw.encode("utf-8")).decode("utf-8")

    def decrypt_text(self, cipher_text: str) -> str:
        try:
            return self._fernet.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("无效加密数据") from exc

    def encrypt_json(self, payload: dict) -> str:
        return self.encrypt_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))

    @staticmethod
    def mask_phone(phone: str) -> str:
        normalized = PrivacyCrypto.normalize_phone(phone)
        if len(normalized) <= 4:
            return "****"
        if len(normalized) <= 7:
            return f"{normalized[:1]}***{normalized[-2:]}"
        return f"{normalized[:3]}****{normalized[-4:]}"

    def _hash(self, namespace: str, raw: str) -> str:
        digest = hmac.new(
            self._hash_secret,
            f"{namespace}:{raw}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return digest

    @staticmethod
    def _build_fernet_key(hash_secret: str, encryption_key: str | None) -> bytes:
        if encryption_key:
            return encryption_key.encode("utf-8")
        digest = hashlib.sha256(hash_secret.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

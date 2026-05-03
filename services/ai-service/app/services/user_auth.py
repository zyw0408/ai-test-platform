from __future__ import annotations

import json
from uuid import uuid4

from app.config import Settings
from app.database import Database
from app.models import UserRole, new_id, utc_now
from app.privacy import PrivacyCrypto
from app.security import hash_password, verify_password
from app.repositories.user_repo import UserRepository


class UserAuthService:
    def __init__(self, db: Database, settings: Settings, repo: UserRepository) -> None:
        self._db = db
        self._settings = settings
        self._repo = repo
        self._privacy = PrivacyCrypto(settings.privacy_hash_secret, settings.privacy_fernet_key)
        self.migrate_legacy_user_identities()

    def migrate_legacy_user_identities(self) -> None:
        rows = self._db.fetchall(
            "SELECT id, password_hash, phone, name, nickname, avatar_url, created_at, updated_at FROM users"
        )
        for row in rows:
            user_id = row["id"]
            created_at = row["created_at"] or utc_now()
            updated_at = row["updated_at"] or created_at
            password_hash_value = row.get("password_hash")
            if isinstance(password_hash_value, str) and password_hash_value:
                exists = self._db.fetchone(
                    "SELECT user_id FROM user_password_credentials WHERE user_id = ?",
                    (user_id,),
                )
                if not exists:
                    self._db.execute(
                        """
                        INSERT INTO user_password_credentials (user_id, password_hash, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (user_id, password_hash_value, created_at, updated_at),
                    )

            legacy_phone = row.get("phone")
            if isinstance(legacy_phone, str) and legacy_phone.strip():
                try:
                    self._upsert_phone_identity(
                        user_id=user_id,
                        phone=legacy_phone,
                        verified_at=updated_at,
                        now=updated_at,
                    )
                    # Remove plaintext phone from legacy column after migration.
                    self._db.execute("UPDATE users SET phone = NULL WHERE id = ?", (user_id,))
                except ValueError:
                    # Skip invalid legacy records and keep migration non-blocking.
                    pass

            if not row.get("nickname") and row.get("name"):
                self._db.execute(
                    "UPDATE users SET nickname = ? WHERE id = ?",
                    (row["name"], user_id),
                )

    def ensure_default_admin(self) -> None:
        existing = self.get_user_by_username(self._settings.default_admin_username)
        if existing:
            return
        self.create_user(
            username=self._settings.default_admin_username,
            password=self._settings.default_admin_password,
            phone=self._settings.default_admin_phone,
            name=self._settings.default_admin_name,
            nickname=self._settings.default_admin_name,
            role="admin",
        )

    def create_user(
        self,
        *,
        username: str,
        password: str,
        phone: str | None,
        name: str,
        nickname: str | None = None,
        avatar_url: str | None = None,
        role: UserRole = "tester",
        is_active: bool = True,
    ) -> dict:
        username = username.strip()
        if not username:
            raise ValueError("username 不能为空")
        if self.get_user_by_username(username):
            raise ValueError("username 已存在")

        phone_normalized = self._normalize_optional_phone(phone)
        if phone_normalized and self.get_user_by_phone(phone_normalized):
            raise ValueError("phone 已存在")

        name = name.strip()
        if not name:
            raise ValueError("name 不能为空")
        nickname_value = (nickname or name).strip() or name
        avatar_value = avatar_url.strip() if isinstance(avatar_url, str) and avatar_url.strip() else None

        now = utc_now()
        user_id = new_id("usr")
        password_hash_value = hash_password(password)
        self._db.execute(
            """
            INSERT INTO users (
                id, username, password_hash, phone, name, nickname, avatar_url, role, is_active,
                created_at, updated_at, last_login_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                password_hash_value,
                None,
                name,
                nickname_value,
                avatar_value,
                role,
                1 if is_active else 0,
                now,
                now,
                None,
            ),
        )
        self._upsert_password_credential(user_id, password_hash_value, now)
        if phone_normalized:
            self._upsert_phone_identity(user_id=user_id, phone=phone_normalized, verified_at=now, now=now)

        return self.get_user_by_id(user_id)  # type: ignore[return-value]

    def authenticate_password(self, username_or_phone: str, password: str) -> dict | None:
        account = username_or_phone.strip()
        if not account:
            return None

        user = self.get_user_by_username(account)
        if not user:
            user = self.get_user_by_phone(account)
        if not user or not user["isActive"]:
            return None

        password_hash_value = self._repo.get_password_hash(user["id"])
        if not isinstance(password_hash_value, str) or not password_hash_value:
            return None

        if not verify_password(password, password_hash_value):
            return None
        return user

    def authenticate_sms(self, phone: str, code: str, *, allow_auto_create: bool = False) -> dict | None:
        phone_normalized = self._normalize_optional_phone(phone)
        if not phone_normalized or not code.strip():
            return None

        user = self.get_user_by_phone(phone_normalized)
        if user and user["isActive"]:
            return user

        if not allow_auto_create:
            return None

        random_suffix = uuid4().hex[:6]
        return self.create_user(
            username=f"sms_{phone_normalized[-4:]}_{random_suffix}",
            password=uuid4().hex,
            phone=phone_normalized,
            name=f"手机用户{phone_normalized[-4:]}",
            nickname=f"手机用户{phone_normalized[-4:]}",
            role="tester",
        )

    def authenticate_wechat(
        self,
        *,
        open_id: str,
        union_id: str | None = None,
        nickname: str | None = None,
        avatar_url: str | None = None,
        profile: dict | None = None,
        allow_auto_create: bool = False,
    ) -> dict:
        openid = open_id.strip()
        if not openid:
            raise ValueError("缺少微信 openId")

        user = self.get_user_by_wechat_openid(openid)
        if not user and union_id:
            user = self.get_user_by_wechat_unionid(union_id)

        if user and not user["isActive"]:
            raise ValueError("当前用户已禁用")

        if not user:
            if not allow_auto_create:
                raise ValueError("该微信账号未注册，请先注册")
            random_suffix = uuid4().hex[:8]
            display_name = (nickname or f"微信用户{random_suffix[:4]}").strip()
            user = self.create_user(
                username=f"wx_{random_suffix}",
                password=uuid4().hex,
                phone=None,
                name=display_name,
                nickname=nickname or display_name,
                avatar_url=avatar_url,
                role="tester",
            )

        return self.bind_wechat(
            user_id=user["id"],
            open_id=openid,
            union_id=union_id,
            nickname=nickname,
            avatar_url=avatar_url,
            profile=profile,
        )

    def bind_wechat(
        self,
        *,
        user_id: str,
        open_id: str,
        union_id: str | None = None,
        nickname: str | None = None,
        avatar_url: str | None = None,
        profile: dict | None = None,
    ) -> dict:
        existing_user = self.get_user_by_id(user_id)
        if not existing_user:
            raise KeyError("user not found")

        openid = open_id.strip()
        if not openid:
            raise ValueError("openId 不能为空")
        unionid = union_id.strip() if union_id else None
        nickname_value = nickname.strip() if isinstance(nickname, str) and nickname.strip() else None
        avatar_value = avatar_url.strip() if isinstance(avatar_url, str) and avatar_url.strip() else None

        openid_hash = self._privacy.hash_wechat_openid(openid)
        unionid_hash = self._privacy.hash_wechat_unionid(unionid) if unionid else None

        conflict = self._db.fetchone(
            "SELECT user_id FROM user_wechat_accounts WHERE openid_hash = ? AND user_id <> ?",
            (openid_hash, user_id),
        )
        if conflict:
            raise ValueError("该微信 openId 已绑定其他用户")
        if unionid_hash:
            union_conflict = self._db.fetchone(
                "SELECT user_id FROM user_wechat_accounts WHERE unionid_hash = ? AND user_id <> ?",
                (unionid_hash, user_id),
            )
            if union_conflict:
                raise ValueError("该微信 unionId 已绑定其他用户")

        now = utc_now()
        existing = self._db.fetchone(
            "SELECT id FROM user_wechat_accounts WHERE user_id = ?",
            (user_id,),
        )
        params = (
            openid_hash,
            self._privacy.encrypt_text(openid),
            unionid_hash,
            self._privacy.encrypt_text(unionid) if unionid else None,
            nickname_value,
            avatar_value,
            self._privacy.encrypt_json(profile) if profile else None,
            now,
            now,
            user_id,
        )
        if existing:
            self._db.execute(
                """
                UPDATE user_wechat_accounts
                SET openid_hash = ?, openid_cipher = ?, unionid_hash = ?, unionid_cipher = ?,
                    nickname = ?, avatar_url = ?, profile_cipher = ?, last_bound_at = ?, updated_at = ?
                WHERE user_id = ?
                """,
                params,
            )
        else:
            self._db.execute(
                """
                INSERT INTO user_wechat_accounts (
                    id, user_id, openid_hash, openid_cipher, unionid_hash, unionid_cipher,
                    nickname, avatar_url, profile_cipher, last_bound_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("uwx"),
                    user_id,
                    openid_hash,
                    self._privacy.encrypt_text(openid),
                    unionid_hash,
                    self._privacy.encrypt_text(unionid) if unionid else None,
                    nickname_value,
                    avatar_value,
                    self._privacy.encrypt_json(profile) if profile else None,
                    now,
                    now,
                    now,
                ),
            )

        if nickname_value or avatar_value:
            self._db.execute(
                "UPDATE users SET nickname = COALESCE(?, nickname), avatar_url = COALESCE(?, avatar_url), updated_at = ? WHERE id = ?",
                (nickname_value, avatar_value, now, user_id),
            )
        return self.get_user_by_id(user_id)  # type: ignore[return-value]

    def unbind_wechat(self, user_id: str) -> dict:
        existing_user = self.get_user_by_id(user_id)
        if not existing_user:
            raise KeyError("user not found")
        self._db.execute("DELETE FROM user_wechat_accounts WHERE user_id = ?", (user_id,))
        return self.get_user_by_id(user_id)  # type: ignore[return-value]

    def touch_last_login(self, user_id: str) -> None:
        now = utc_now()
        self._db.execute(
            "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
            (now, now, user_id),
        )

    def record_login_event(
        self,
        *,
        user_id: str | None,
        method: str,
        success: bool,
        detail: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self._db.execute(
            """
            INSERT INTO user_login_events (id, user_id, method, success, ip, user_agent, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("ule"),
                user_id,
                method,
                1 if success else 0,
                ip,
                user_agent,
                detail,
                utc_now(),
            ),
        )

    def get_user_by_id(self, user_id: str) -> dict | None:
        row = self._repo.get_by_id(user_id)
        return self._to_public_user(row) if row else None

    def get_user_by_username(self, username: str) -> dict | None:
        row = self._repo.get_by_username(username.strip())
        return self._to_public_user(row) if row else None

    def get_user_by_phone(self, phone: str) -> dict | None:
        normalized = self._normalize_optional_phone(phone)
        if not normalized:
            return None
        row = self._repo.get_by_phone_hash(self._privacy.hash_phone(normalized))
        return self._to_public_user(row) if row else None

    def get_user_by_wechat_openid(self, open_id: str) -> dict | None:
        row = self._repo.get_by_wechat_openid_hash(self._privacy.hash_wechat_openid(open_id))
        return self._to_public_user(row) if row else None

    def get_user_by_wechat_unionid(self, union_id: str) -> dict | None:
        row = self._repo.get_by_wechat_unionid_hash(self._privacy.hash_wechat_unionid(union_id))
        return self._to_public_user(row) if row else None

    def list_users(self) -> list[dict]:
        rows = self._repo.list_all()
        return [self._to_public_user(row) for row in rows]

    def update_user(
        self,
        user_id: str,
        *,
        password: str | None = None,
        phone: str | None = None,
        name: str | None = None,
        nickname: str | None = None,
        avatar_url: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> dict:
        existing = self._db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        if not existing:
            raise KeyError("user not found")

        now = utc_now()
        patch: dict[str, object] = {}
        if name is not None:
            name_value = name.strip()
            if not name_value:
                raise ValueError("name 不能为空")
            patch["name"] = name_value
        if nickname is not None:
            nickname_value = nickname.strip()
            patch["nickname"] = nickname_value or None
        if avatar_url is not None:
            avatar_value = avatar_url.strip() or None
            patch["avatar_url"] = avatar_value
        if role is not None:
            patch["role"] = role
        if is_active is not None:
            patch["is_active"] = 1 if is_active else 0

        if patch:
            patch["updated_at"] = now
            columns = ", ".join(f"{key} = ?" for key in patch.keys())
            values = tuple(patch.values())
            self._db.execute(
                f"UPDATE users SET {columns} WHERE id = ?",
                values + (user_id,),
            )

        if password is not None:
            password_hash_value = hash_password(password)
            self._db.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (password_hash_value, now, user_id),
            )
            self._upsert_password_credential(user_id, password_hash_value, now)

        if phone is not None:
            normalized_phone = self._normalize_optional_phone(phone)
            if normalized_phone:
                self._upsert_phone_identity(user_id=user_id, phone=normalized_phone, verified_at=now, now=now)
            else:
                self._db.execute("DELETE FROM user_phone_identities WHERE user_id = ?", (user_id,))
                self._db.execute("UPDATE users SET phone = NULL, updated_at = ? WHERE id = ?", (now, user_id))

        result = self.get_user_by_id(user_id)
        if not result:
            raise KeyError("user not found")
        return result

    def _upsert_password_credential(self, user_id: str, password_hash_value: str, now: str) -> None:
        existing = self._db.fetchone(
            "SELECT user_id FROM user_password_credentials WHERE user_id = ?",
            (user_id,),
        )
        if existing:
            self._db.execute(
                "UPDATE user_password_credentials SET password_hash = ?, updated_at = ? WHERE user_id = ?",
                (password_hash_value, now, user_id),
            )
            return
        self._db.execute(
            """
            INSERT INTO user_password_credentials (user_id, password_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, password_hash_value, now, now),
        )

    def _upsert_phone_identity(
        self,
        *,
        user_id: str,
        phone: str,
        verified_at: str | None,
        now: str,
    ) -> None:
        normalized = self._privacy.normalize_phone(phone)
        phone_hash = self._privacy.hash_phone(normalized)
        conflict = self._db.fetchone(
            "SELECT user_id FROM user_phone_identities WHERE phone_hash = ? AND user_id <> ?",
            (phone_hash, user_id),
        )
        if conflict:
            raise ValueError("phone 已存在")

        existing = self._db.fetchone(
            "SELECT id FROM user_phone_identities WHERE user_id = ?",
            (user_id,),
        )
        phone_cipher = self._privacy.encrypt_text(normalized)
        phone_last4 = normalized[-4:] if len(normalized) >= 4 else normalized
        if existing:
            self._db.execute(
                """
                UPDATE user_phone_identities
                SET phone_hash = ?, phone_cipher = ?, phone_last4 = ?, verified_at = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (phone_hash, phone_cipher, phone_last4, verified_at, now, user_id),
            )
        else:
            self._db.execute(
                """
                INSERT INTO user_phone_identities (
                    id, user_id, phone_hash, phone_cipher, phone_last4, verified_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (new_id("uph"), user_id, phone_hash, phone_cipher, phone_last4, verified_at, now, now),
            )

    def _normalize_optional_phone(self, phone: str | None) -> str | None:
        if phone is None:
            return None
        normalized = self._privacy.normalize_phone(phone)
        return normalized or None

    def get_user_settings(self, user_id: str) -> dict:
        user = self._repo.get_by_id(user_id)
        if not user:
            raise KeyError("user not found")
        try:
            return json.loads(user.get("settings_json") or "{}")
        except (ValueError, TypeError, json.JSONDecodeError):
            return {}

    def update_user_settings(self, user_id: str, settings: dict) -> None:
        self._repo.update_settings(user_id, json.dumps(settings), utc_now())

    def _to_public_user(self, row: dict) -> dict:
        phone_last4 = row.get("phone_last4")
        if phone_last4:
            phone_display = f"***{phone_last4}"
        else:
            legacy_phone = row.get("phone")
            phone_display = (
                self._privacy.mask_phone(legacy_phone)
                if isinstance(legacy_phone, str) and legacy_phone.strip()
                else None
            )

        return {
            "id": row["id"],
            "username": row["username"],
            "phone": phone_display,
            "name": row["name"],
            "nickname": row.get("effective_nickname"),
            "avatarUrl": row.get("effective_avatar_url"),
            "wechatBound": bool(row.get("wechat_bound")),
            "role": row["role"],
            "isActive": bool(row["is_active"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "lastLoginAt": row.get("last_login_at"),
        }

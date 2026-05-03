from typing import Any, List, Optional, Dict
from app.database import Database
from app.models import utc_now

class UserRepository:
    _USER_SELECT = """
        SELECT
            u.*,
            p.phone_last4 AS phone_last4,
            CASE WHEN p.user_id IS NULL THEN 0 ELSE 1 END AS phone_bound,
            CASE WHEN w.user_id IS NULL THEN 0 ELSE 1 END AS wechat_bound,
            COALESCE(w.nickname, u.nickname) AS effective_nickname,
            COALESCE(w.avatar_url, u.avatar_url) AS effective_avatar_url
        FROM users u
        LEFT JOIN user_phone_identities p ON p.user_id = u.id
        LEFT JOIN user_wechat_accounts w ON w.user_id = u.id
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def _query(self, sql_sqlite: str, sql_postgres: str) -> str:
        return sql_sqlite if hasattr(self._db, "dialect") and self._db.dialect == "sqlite" else sql_postgres

    def get_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        query = f"{self._USER_SELECT} WHERE u.id = ?" 
        row = self._db.fetchone(query, (user_id,))
        return dict(row) if row else None

    def get_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        query = f"{self._USER_SELECT} WHERE u.username = ?" 
        row = self._db.fetchone(query, (username,))
        return dict(row) if row else None

    def get_by_phone_hash(self, phone_hash: str) -> Optional[Dict[str, Any]]:
        query = f"{self._USER_SELECT} WHERE p.phone_hash = ?"
        row = self._db.fetchone(query, (phone_hash,))
        return dict(row) if row else None

    def get_by_wechat_openid_hash(self, openid_hash: str) -> Optional[Dict[str, Any]]:
        query = f"{self._USER_SELECT} WHERE w.openid_hash = ?"
        row = self._db.fetchone(query, (openid_hash,))
        return dict(row) if row else None

    def get_by_wechat_unionid_hash(self, unionid_hash: str) -> Optional[Dict[str, Any]]:
        query = f"{self._USER_SELECT} WHERE w.unionid_hash = ?"
        row = self._db.fetchone(query, (unionid_hash,))
        return dict(row) if row else None

    def list_all(self) -> List[Dict[str, Any]]:
        rows = self._db.fetchall(f"{self._USER_SELECT} ORDER BY u.created_at DESC")
        return [dict(row) for row in rows]

    def update_settings(self, user_id: str, settings_json: str, now: str) -> None:
        query = "UPDATE users SET settings_json = ?, updated_at = ? WHERE id = ?"
        self._db.execute(query, (settings_json, now, user_id))

    def update_profile(self, user_id: str, data: Dict[str, Any]) -> None:
        if not data:
            return
        data["updated_at"] = utc_now()
        cols = [f"{k} = ?" for k in data.keys()]
        vals = list(data.values())
        vals.append(user_id)
        query = f"UPDATE users SET {', '.join(cols)} WHERE id = ?"
        self._db.execute(query, tuple(vals))

    def get_password_hash(self, user_id: str) -> Optional[str]:
        query = "SELECT password_hash FROM user_password_credentials WHERE user_id = ?"
        row = self._db.fetchone(query, (user_id,))
        if row:
            return row["password_hash"]
        # Legacy fallback
        query = "SELECT password_hash FROM users WHERE id = ?"
        row = self._db.fetchone(query, (user_id,))
        return row["password_hash"] if row else None

    def upsert_password_credential(self, user_id: str, password_hash: str, now: str) -> None:
        exists = self._db.fetchone("SELECT user_id FROM user_password_credentials WHERE user_id = ?", (user_id,))
        if exists:
            self._db.execute(
                "UPDATE user_password_credentials SET password_hash = ?, updated_at = ? WHERE user_id = ?",
                (password_hash, now, user_id)
            )
        else:
            self._db.execute(
                "INSERT INTO user_password_credentials (user_id, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (user_id, password_hash, now, now)
            )

    def record_login_event(self, event_id: str, data: Dict[str, Any]) -> None:
        cols = ["id"] + list(data.keys())
        placeholders = ["?"] * len(cols)
        vals = [event_id] + list(data.values())
        query = f"INSERT INTO user_login_events ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
        self._db.execute(query, tuple(vals))

    def touch_last_login(self, user_id: str, now: str) -> None:
        self._db.execute("UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?", (now, now, user_id))
    def upsert_phone_identity(self, identity_id: str, data: Dict[str, Any]) -> None:
        user_id = data.get("user_id")
        exists = self._db.fetchone("SELECT id FROM user_phone_identities WHERE user_id = ?", (user_id,))
        if exists:
            cols = [f"{k} = ?" for k in data.keys()]
            query = f"UPDATE user_phone_identities SET {', '.join(cols)} WHERE user_id = ?"
            self._db.execute(query, tuple(data.values()) + (user_id,))
        else:
            data["id"] = identity_id
            cols = list(data.keys())
            placeholders = ["?"] * len(cols)
            query = f"INSERT INTO user_phone_identities ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
            self._db.execute(query, tuple(data.values()))

    def upsert_wechat_account(self, account_id: str, data: Dict[str, Any]) -> None:
        user_id = data.get("user_id")
        exists = self._db.fetchone("SELECT id FROM user_wechat_accounts WHERE user_id = ?", (user_id,))
        if exists:
            cols = [f"{k} = ?" for k in data.keys()]
            query = f"UPDATE user_wechat_accounts SET {', '.join(cols)} WHERE user_id = ?"
            self._db.execute(query, tuple(data.values()) + (user_id,))
        else:
            data["id"] = account_id
            cols = list(data.keys())
            placeholders = ["?"] * len(cols)
            query = f"INSERT INTO user_wechat_accounts ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
            self._db.execute(query, tuple(data.values()))

    def delete_wechat_account(self, user_id: str) -> None:
        self._db.execute("DELETE FROM user_wechat_accounts WHERE user_id = ?", (user_id,))

    def delete_phone_identity(self, user_id: str) -> None:
        self._db.execute("DELETE FROM user_phone_identities WHERE user_id = ?", (user_id,))

    def get_ai_settings(self, user_id: str) -> Optional[Dict[str, Any]]:
        row = self._db.fetchone("SELECT settings_json FROM users WHERE id = ?", (user_id,))
        if not row or not row["settings_json"]:
            return None
        import json
        try:
            return json.loads(row["settings_json"])
        except:
            return None

    def create_user_record(self, data: Dict[str, Any]) -> None:
        cols = list(data.keys())
        placeholders = ["?"] * len(cols)
        query = f"INSERT INTO users ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
        self._db.execute(query, tuple(data.values()))

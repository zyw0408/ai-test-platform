from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from app.config import Settings

try:  # pragma: no cover - optional dependency in local test environments
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
except Exception:  # pragma: no cover - allow sqlite-only environments
    psycopg = None
    dict_row = None
    ConnectionPool = None


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        phone TEXT UNIQUE,
        name TEXT NOT NULL,
        nickname TEXT,
        avatar_url TEXT,
        role TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_login_at TEXT,
        settings_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_password_credentials (
        user_id TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entities (
        id TEXT PRIMARY KEY,
        collection TEXT NOT NULL,
        payload TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_phone_identities (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL UNIQUE,
        phone_hash TEXT NOT NULL UNIQUE,
        phone_cipher TEXT,
        phone_last4 TEXT NOT NULL,
        verified_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_wechat_accounts (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL UNIQUE,
        openid_hash TEXT NOT NULL UNIQUE,
        openid_cipher TEXT,
        unionid_hash TEXT UNIQUE,
        unionid_cipher TEXT,
        nickname TEXT,
        avatar_url TEXT,
        profile_cipher TEXT,
        last_bound_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_login_events (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        method TEXT NOT NULL,
        success INTEGER NOT NULL,
        ip TEXT,
        user_agent TEXT,
        detail TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS organizations (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        slug TEXT UNIQUE,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS teams (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(org_id) REFERENCES organizations(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS requirements (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        source_spec_id TEXT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        tags_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'draft',
        latest_analysis_version INTEGER,
        version INTEGER NOT NULL DEFAULT 1, -- 为并发控制增加版本号
        created_by TEXT,
        deleted_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        created_by TEXT,
        deleted_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(org_id) REFERENCES organizations(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cases (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        spec_id TEXT,
        requirement_id TEXT,
        title TEXT NOT NULL,
        objective TEXT NOT NULL DEFAULT '',
        preconditions TEXT NOT NULL DEFAULT '',
        steps_json TEXT NOT NULL DEFAULT '[]',
        assertion_hints_json TEXT NOT NULL DEFAULT '[]',
        payload_json TEXT NOT NULL DEFAULT '{}',
        tags_json TEXT NOT NULL DEFAULT '[]',
        priority TEXT NOT NULL DEFAULT 'P2',
        status TEXT NOT NULL DEFAULT 'draft',
        kind TEXT NOT NULL DEFAULT 'manual',
        version INTEGER NOT NULL DEFAULT 1,
        created_by TEXT,
        deleted_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY(requirement_id) REFERENCES requirements(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_specs (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        title TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'swagger',
        content TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_by TEXT,
        deleted_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_requirements_project_created
    ON requirements(project_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_requirements_active_project_updated
    ON requirements(project_id, deleted_at, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_requirements_active_status_updated
    ON requirements(status, deleted_at, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_requirements_deleted_updated
    ON requirements(deleted_at, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_requirements_project_status_updated
    ON requirements(project_id, status, deleted_at, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_requirements_dedupe_ci
    ON requirements(project_id, deleted_at, lower(title), lower(content))
    """,
    """
    CREATE TABLE IF NOT EXISTS requirement_analysis_versions (
        id TEXT PRIMARY KEY,
        requirement_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        analysis_json TEXT NOT NULL,
        ai_operation_id TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(requirement_id, version),
        FOREIGN KEY(requirement_id) REFERENCES requirements(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_req_analysis_requirement_created
    ON requirement_analysis_versions(requirement_id, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_operations (
        id TEXT PRIMARY KEY,
        operation_type TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        status TEXT NOT NULL,
        request_payload TEXT,
        response_payload TEXT,
        error_message TEXT,
        created_by TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_operations_target
    ON ai_operations(target_type, target_id, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS api_collections (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        variables_json TEXT NOT NULL DEFAULT '{}',
        version INTEGER NOT NULL DEFAULT 1,
        created_by TEXT,
        deleted_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_api_collections_project_updated
    ON api_collections(project_id, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_api_collections_project_deleted_updated
    ON api_collections(project_id, deleted_at, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS api_requests (
        id TEXT PRIMARY KEY,
        collection_id TEXT NOT NULL,
        parent_id TEXT,
        name TEXT NOT NULL,
        group_name TEXT NOT NULL DEFAULT 'default',
        tags_json TEXT NOT NULL DEFAULT '[]',
        method TEXT NOT NULL,
        url TEXT NOT NULL,
        query_json TEXT NOT NULL DEFAULT '[]',
        headers_json TEXT NOT NULL DEFAULT '[]',
        body_mode TEXT NOT NULL DEFAULT 'none',
        body_raw TEXT NOT NULL DEFAULT '',
        body_form_json TEXT NOT NULL DEFAULT '[]',
        auth_type TEXT NOT NULL DEFAULT 'none',
        auth_json TEXT NOT NULL DEFAULT '{}',
        verify_ssl INTEGER NOT NULL DEFAULT 1,
        tls_json TEXT NOT NULL DEFAULT '{}',
        tests_json TEXT NOT NULL DEFAULT '[]',
        pre_script TEXT NOT NULL DEFAULT '',
        test_script TEXT NOT NULL DEFAULT '',
        is_folder INTEGER NOT NULL DEFAULT 0,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_by TEXT,
        deleted_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_api_requests_collection_sort
    ON api_requests(collection_id, sort_order ASC, created_at ASC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_api_requests_collection_deleted_sort
    ON api_requests(collection_id, deleted_at, sort_order ASC, created_at ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS api_environments (
        id TEXT PRIMARY KEY,
        collection_id TEXT NOT NULL,
        name TEXT NOT NULL,
        variables_json TEXT NOT NULL DEFAULT '{}',
        is_default INTEGER NOT NULL DEFAULT 0,
        created_by TEXT,
        deleted_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_api_env_collection_updated
    ON api_environments(collection_id, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_api_env_collection_deleted_default_updated
    ON api_environments(collection_id, deleted_at, is_default DESC, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS api_request_runs (
        id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL,
        collection_id TEXT NOT NULL,
        method TEXT NOT NULL,
        url TEXT NOT NULL,
        status_code INTEGER,
        duration_ms INTEGER NOT NULL DEFAULT 0,
        success INTEGER NOT NULL DEFAULT 0,
        response_headers_json TEXT NOT NULL DEFAULT '{}',
        response_body TEXT NOT NULL DEFAULT '',
        response_size INTEGER NOT NULL DEFAULT 0,
        error_message TEXT,
        assertions_json TEXT NOT NULL DEFAULT '[]',
        meta_json TEXT NOT NULL DEFAULT '{}',
        created_by TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_api_runs_collection_created
    ON api_request_runs(collection_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_api_runs_request_created
    ON api_request_runs(request_id, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id TEXT PRIMARY KEY,
        actor_id TEXT,
        action TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        payload_json TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_logs_target
    ON audit_logs(target_type, target_id, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_chat_messages (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        session_id TEXT,
        project_id TEXT,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        model TEXT,
        task_type TEXT,
        agent_key TEXT,
        token_estimate INTEGER NOT NULL DEFAULT 0,
        meta_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_chat_messages_user_created
    ON ai_chat_messages(user_id, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_chat_sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        project_id TEXT,
        title TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        summary_updated_at TEXT,
        message_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_chat_sessions_user_updated
    ON ai_chat_sessions(user_id, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_prompt_templates (
        id TEXT PRIMARY KEY,
        task_type TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        instruction TEXT NOT NULL,
        output_contract TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_prompt_templates_enabled
    ON ai_prompt_templates(enabled, task_type)
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_agents (
        id TEXT PRIMARY KEY,
        key TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        prompt_template_id TEXT,
        allowed_tools_json TEXT NOT NULL DEFAULT '[]',
        enabled INTEGER NOT NULL DEFAULT 1,
        priority INTEGER NOT NULL DEFAULT 100,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_agents_enabled_priority
    ON ai_agents(enabled, priority ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_hooks (
        id TEXT PRIMARY KEY,
        key TEXT NOT NULL UNIQUE,
        stage TEXT NOT NULL,
        title TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        config_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_hooks_stage_enabled
    ON ai_hooks(stage, enabled)
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_plugins (
        id TEXT PRIMARY KEY,
        key TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        type TEXT NOT NULL,
        config_json TEXT NOT NULL DEFAULT '{}',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_plugins_type_enabled
    ON ai_plugins(type, enabled)
    """,
    """
    CREATE TABLE IF NOT EXISTS security_findings (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        scan_id TEXT,
        signature TEXT NOT NULL,
        type TEXT NOT NULL,
        severity TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        method TEXT NOT NULL,
        description TEXT NOT NULL,
        evidence TEXT,
        remediation TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        resolved_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(project_id, signature)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_security_findings_project_updated
    ON security_findings(project_id, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS vector_documents (
        id TEXT PRIMARY KEY,
        project_id TEXT,
        module TEXT NOT NULL,
        source_id TEXT NOT NULL,
        chunk_index INTEGER NOT NULL DEFAULT 0,
        title TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL,
        embedding_json TEXT NOT NULL,
        meta_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_vector_documents_project_module
    ON vector_documents(project_id, module, source_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS team_members (
        id TEXT PRIMARY KEY,
        team_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'member', -- owner, admin, member
        created_at TEXT NOT NULL,
        FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(team_id, user_id)
    )
    """,
]


class Database(Protocol):
    @property
    def dialect(self) -> str: ...
    def init_schema(self) -> None: ...
    def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None: ...
    def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]: ...
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> int: ...

MultiTenantDB = Database


class SQLiteDatabase:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def init_schema(self) -> None:
        with self._connect() as connection:
            for statement in _SCHEMA_STATEMENTS:
                connection.execute(statement)
            self._ensure_column(connection, "users", "nickname", "TEXT")
            self._ensure_column(connection, "users", "avatar_url", "TEXT")
            self._ensure_column(connection, "users", "settings_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(connection, "requirements", "deleted_at", "TEXT")
            self._ensure_column(
                connection,
                "api_collections",
                "variables_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                connection,
                "api_requests",
                "group_name",
                "TEXT NOT NULL DEFAULT 'default'",
            )
            self._ensure_column(
                connection,
                "api_requests",
                "tags_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(
                connection,
                "api_requests",
                "verify_ssl",
                "INTEGER NOT NULL DEFAULT 1",
            )
            self._ensure_column(
                connection,
                "api_requests",
                "tls_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                connection,
                "api_request_runs",
                "meta_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(connection, "ai_chat_messages", "session_id", "TEXT")
            self._ensure_column(connection, "ai_chat_messages", "project_id", "TEXT")
            self._ensure_column(connection, "ai_chat_messages", "task_type", "TEXT")
            self._ensure_column(connection, "ai_chat_messages", "agent_key", "TEXT")
            self._ensure_column(connection, "ai_chat_messages", "token_estimate", "INTEGER NOT NULL DEFAULT 0")
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ai_chat_messages_session_created
                ON ai_chat_messages(session_id, created_at ASC)
                """
            )
            self._ensure_column(connection, "requirements", "org_id", "TEXT")
            self._ensure_column(connection, "requirements", "version", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(connection, "api_collections", "org_id", "TEXT")
            self._ensure_column(connection, "api_collections", "version", "INTEGER NOT NULL DEFAULT 1")
            # Ensure tables with org_id for data migration
            self._ensure_column(connection, "projects", "org_id", "TEXT")
            self._ensure_column(connection, "cases", "org_id", "TEXT")
            self._ensure_column(connection, "source_specs", "org_id", "TEXT")

            # --- 数据领养与修复逻辑 (Data Repair) ---
            now = _utc_now()
            try:
                connection.execute(
                    "INSERT OR IGNORE INTO organizations (id, name, slug, created_at, updated_at) VALUES ('DEFAULT_ORG', 'My Default Organization', 'default', ?, ?)",
                    (now, now),
                )
                connection.execute("UPDATE requirements SET org_id = 'DEFAULT_ORG' WHERE org_id IS NULL OR org_id = ''")
                connection.execute("UPDATE api_collections SET org_id = 'DEFAULT_ORG' WHERE org_id IS NULL OR org_id = ''")
            except Exception as e:
                # SQLite 锁冲突虽然少见但仍需捕获
                if "locked" in str(e).lower():
                    print(f"[INFO] SQLite 数据库繁忙，跳过并发迁移: {e}")
                else:
                    raise e

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_api_requests_collection_group
                ON api_requests(collection_id, group_name, sort_order ASC)
                """
            )
            
            # --- Data Migration from entities table to structured tables ---
            import json
            now = _utc_now()
            
            # Migrate projects
            rows = connection.execute("SELECT payload FROM entities WHERE collection = 'projects' AND deleted_at IS NULL").fetchall()
            for row in rows:
                try:
                    p = json.loads(row[0])
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO projects (id, org_id, name, description, created_by, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (p["id"], p.get("org_id", "DEFAULT_ORG"), p["name"], p.get("description", ""), p.get("createdBy"), p.get("createdAt", now), p.get("updatedAt", now))
                    )
                except Exception:
                    continue
            
            # Migrate cases
            rows = connection.execute("SELECT payload FROM entities WHERE collection = 'cases' AND deleted_at IS NULL").fetchall()
            for row in rows:
                try:
                    c = json.loads(row[0])
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO cases (id, org_id, project_id, spec_id, requirement_id, title, kind, priority, status, steps_json, created_by, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (c["id"], c.get("org_id", "DEFAULT_ORG"), c.get("projectId"), c.get("specId"), c.get("requirementId"), c.get("name") or c.get("title"), c.get("type") or c.get("kind", "manual"), c.get("priority", "P1"), c.get("status", "draft"), json.dumps(c.get("steps") or []), c.get("createdBy"), c.get("createdAt", now), c.get("updatedAt", now))
                    )
                except Exception:
                    continue

            # Migrate source_specs
            rows = connection.execute("SELECT payload FROM entities WHERE collection = 'source_specs' AND deleted_at IS NULL").fetchall()
            for row in rows:
                try:
                    s = json.loads(row[0])
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO source_specs (id, org_id, project_id, title, kind, content, metadata_json, created_by, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (s["id"], s.get("org_id", "DEFAULT_ORG"), s.get("projectId"), s.get("name") or s.get("title"), s.get("type") or s.get("kind", "swagger"), s.get("content", ""), json.dumps(s.get("metadata", s.get("metadata_json", {}))), s.get("createdBy"), s.get("createdAt", now), s.get("updatedAt", now))
                    )
                except Exception:
                    continue

            connection.commit()

    def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._connect() as connection:
            cursor = connection.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None

    def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._connect() as connection:
            cursor = connection.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> int:
        with self._connect() as connection:
            cursor = connection.execute(query, params)
            connection.commit()
            return cursor.rowcount

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.execute("PRAGMA cache_size = -20000")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_type: str,
    ) -> None:
        cursor = connection.execute(f"PRAGMA table_info({table_name})")
        columns = {row[1] for row in cursor.fetchall()}
        if column_name in columns:
            return
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    @property
    def dialect(self) -> str:
        return "sqlite"


class PostgresDatabase:
    def __init__(self, database_url: str, connect_timeout_seconds: int = 3) -> None:
        if psycopg is None or dict_row is None:
            raise RuntimeError(
                "未安装 psycopg，无法连接 PostgreSQL。请先安装 `psycopg[binary]`。"
            )
        self._database_url = database_url
        self._connect_timeout_seconds = max(int(connect_timeout_seconds), 1)
        self._pool: ConnectionPool | None = None

    def _get_pool(self) -> ConnectionPool:
        if self._pool is None:
            if ConnectionPool is None:
                raise RuntimeError("psycopg_pool 未安装")
            self._pool = ConnectionPool(
                self._database_url,
                kwargs={
                    "row_factory": dict_row,
                    "connect_timeout": self._connect_timeout_seconds,
                },
                min_size=2,
                max_size=10,
                open=True,
            )
        return self._pool

    def _connect(self):
        return self._get_pool().connection()

    def init_schema(self) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for statement in _SCHEMA_STATEMENTS:
                    cursor.execute(statement)
                self._ensure_column(
                    cursor=cursor,
                    table_name="users",
                    column_name="nickname",
                    column_type="TEXT",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="users",
                    column_name="avatar_url",
                    column_type="TEXT",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="requirements",
                    column_name="deleted_at",
                    column_type="TEXT",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="users",
                    column_name="settings_json",
                    column_type="TEXT NOT NULL DEFAULT '{}'",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="api_collections",
                    column_name="variables_json",
                    column_type="TEXT NOT NULL DEFAULT '{}'",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="api_requests",
                    column_name="group_name",
                    column_type="TEXT NOT NULL DEFAULT 'default'",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="api_requests",
                    column_name="tags_json",
                    column_type="TEXT NOT NULL DEFAULT '[]'",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="api_requests",
                    column_name="verify_ssl",
                    column_type="INTEGER NOT NULL DEFAULT 1",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="api_requests",
                    column_name="tls_json",
                    column_type="TEXT NOT NULL DEFAULT '{}'",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="api_request_runs",
                    column_name="meta_json",
                    column_type="TEXT NOT NULL DEFAULT '{}'",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="ai_chat_messages",
                    column_name="session_id",
                    column_type="TEXT",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="ai_chat_messages",
                    column_name="project_id",
                    column_type="TEXT",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="ai_chat_messages",
                    column_name="task_type",
                    column_type="TEXT",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="ai_chat_messages",
                    column_name="agent_key",
                    column_type="TEXT",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="ai_chat_messages",
                    column_name="token_estimate",
                    column_type="INTEGER NOT NULL DEFAULT 0",
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_ai_chat_messages_session_created
                    ON ai_chat_messages(session_id, created_at ASC)
                    """
                )

                # --- cases 表缺失列修复 ---
                self._ensure_column(
                    cursor=cursor,
                    table_name="cases",
                    column_name="objective",
                    column_type="TEXT NOT NULL DEFAULT ''",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="cases",
                    column_name="preconditions",
                    column_type="TEXT NOT NULL DEFAULT ''",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="cases",
                    column_name="steps_json",
                    column_type="TEXT NOT NULL DEFAULT '[]'",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="cases",
                    column_name="assertion_hints_json",
                    column_type="TEXT NOT NULL DEFAULT '[]'",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="cases",
                    column_name="payload_json",
                    column_type="TEXT NOT NULL DEFAULT '{}'",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="cases",
                    column_name="org_id",
                    column_type="TEXT",
                )

                # --- 核心协作隔离迁移 (Core Migration) ---
                self._ensure_column(
                    cursor=cursor,
                    table_name="requirements",
                    column_name="org_id",
                    column_type="TEXT",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="requirements",
                    column_name="version",
                    column_type="INTEGER NOT NULL DEFAULT 1",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="api_collections",
                    column_name="org_id",
                    column_type="TEXT",
                )
                self._ensure_column(
                    cursor=cursor,
                    table_name="api_collections",
                    column_name="version",
                    column_type="INTEGER NOT NULL DEFAULT 1",
                )

                # --- 数据领养与修复逻辑 (Data Repair) ---
                # 1. 确保有一个默认组织 (显式提供时间戳，防止 Postgres 默认值失效报错)
                now = _utc_now()
                try:
                    cursor.execute(
                        """
                        INSERT INTO organizations (id, name, slug, created_at, updated_at) 
                        VALUES ('DEFAULT_ORG', 'My Default Organization', 'default', %s, %s) 
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (now, now),
                    )
                    
                    # 2. 将所有孤儿数据归属到默认组织
                    cursor.execute("UPDATE requirements SET org_id = 'DEFAULT_ORG' WHERE org_id IS NULL")
                    cursor.execute("UPDATE api_collections SET org_id = 'DEFAULT_ORG' WHERE org_id IS NULL")
                    
                    # 3. 领养 entities 中的 projects, cases, source_specs (如果存在)
                    import json
                    try:
                        # Migrate projects
                        cursor.execute("SELECT payload FROM entities WHERE collection = 'projects' AND deleted_at IS NULL")
                        for (payload_str,) in cursor.fetchall():
                            p = json.loads(payload_str)
                            cursor.execute(
                                """
                                INSERT INTO projects (id, org_id, name, description, created_by, created_at, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (id) DO NOTHING
                                """,
                                (p["id"], p.get("org_id", "DEFAULT_ORG"), p["name"], p.get("description", ""), p.get("createdBy"), p.get("createdAt", now), p.get("updatedAt", now))
                            )
                        
                        # Migrate cases
                        cursor.execute("SELECT payload FROM entities WHERE collection = 'cases' AND deleted_at IS NULL")
                        for (payload_str,) in cursor.fetchall():
                            c = json.loads(payload_str)
                            cursor.execute(
                                """
                                INSERT INTO cases (id, org_id, project_id, spec_id, requirement_id, title, kind, priority, status, steps_json, created_by, created_at, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (id) DO NOTHING
                                """,
                                (c["id"], c.get("org_id", "DEFAULT_ORG"), c.get("projectId"), c.get("specId"), c.get("requirementId"), c.get("name") or c.get("title"), c.get("type") or c.get("kind", "manual"), c.get("priority", "P1"), c.get("status", "draft"), json.dumps(c.get("steps") or []), c.get("createdBy"), c.get("createdAt", now), c.get("updatedAt", now))
                            )

                        # Migrate source_specs
                        cursor.execute("SELECT payload FROM entities WHERE collection = 'source_specs' AND deleted_at IS NULL")
                        for (payload_str,) in cursor.fetchall():
                            s = json.loads(payload_str)
                            cursor.execute(
                                """
                                INSERT INTO source_specs (id, org_id, project_id, title, kind, content, metadata_json, created_by, created_at, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (id) DO NOTHING
                                """,
                                (s["id"], s.get("org_id", "DEFAULT_ORG"), s.get("projectId"), s.get("name") or s.get("title"), s.get("type") or s.get("kind", "swagger"), s.get("content", ""), json.dumps(s.get("metadata", s.get("metadata_json", {}))), s.get("createdBy"), s.get("createdAt", now), s.get("updatedAt", now))
                            )
                    except Exception as e:
                        logger.warning(f"Failed to migrate entities: {e}")
                
                    # 3. 如果表刚增加 version 字段，可能需要初始化 (如果是 Postgres 且 DEFAULT 1 已经生效则不需要)
                except Exception as e:
                    # 如果是因为其他进程正在迁移导致的锁冲突，直接忽略，因为最终一致性
                    if "deadlock" in str(e).lower() or "lock timeout" in str(e).lower():
                        print(f"[INFO] 数据库迁移中检测到并发冲突 (Deadlock/Lock)，跳过当前进程: {e}")
                    else:
                        raise e
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_api_requests_collection_group
                    ON api_requests(collection_id, group_name, sort_order ASC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_requirements_fts
                    ON requirements
                    USING GIN (
                        to_tsvector(
                            'simple',
                            COALESCE(title, '') || ' ' || COALESCE(content, '') || ' ' || COALESCE(tags_json, '')
                        )
                    )
                    """
                )

    def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._adapt_query(query), params)
                row = cursor.fetchone()
                return dict(row) if row else None

    def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._adapt_query(query), params)
                return [dict(row) for row in cursor.fetchall()]

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> int:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._adapt_query(query), params)
                return cursor.rowcount

    @property
    def dialect(self) -> str:
        return "postgres"

    @staticmethod
    def _adapt_query(query: str) -> str:
        return re.sub(r"\?", "%s", query)

    @staticmethod
    def _ensure_column(
        *,
        cursor: Any,
        table_name: str,
        column_name: str,
        column_type: str,
    ) -> None:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = %s
            """,
            (table_name, column_name),
        )
        if cursor.fetchone():
            return
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        )


def build_database(settings: Settings) -> Database:
    print(f"DEBUG: database_url type={type(settings.database_url)} value={settings.database_url!r}")
    if settings.database_url:
        print("DEBUG: entering postgres branch")
        normalized = settings.database_url.strip().lower()
        if normalized.startswith("postgres://") or normalized.startswith("postgresql://"):
            return PostgresDatabase(
                settings.database_url,
                connect_timeout_seconds=settings.database_connect_timeout_seconds,
            )
        raise ValueError("AI_SERVICE_DATABASE_URL 仅支持 postgres/postgresql 连接串")
    print("DEBUG: entering sqlite branch")
    return SQLiteDatabase(settings.db_path)

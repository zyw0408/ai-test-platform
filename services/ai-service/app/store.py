from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from app.database import Database, SQLiteDatabase


class JsonStore:
    def __init__(
        self,
        base_dir: Path,
        *,
        db: Database | None = None,
        db_path: Path | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = (db_path or (self.base_dir / "platform.db")).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = db or SQLiteDatabase(self.db_path)
        self._lock = Lock()
        self._collections = (
            "projects",
            "specs",
            "cases",
            "runs",
            "performance_runs",
            "artifacts",
            "system",
            "requirements",
        )
        self._legacy_files = {
            "projects": self.base_dir / "projects.json",
            "specs": self.base_dir / "specs.json",
            "cases": self.base_dir / "cases.json",
            "runs": self.base_dir / "runs.json",
            "performance_runs": self.base_dir / "performance_runs.json",
            "artifacts": self.base_dir / "artifacts.json",
            "system": self.base_dir / "system.json",
            "requirements": self.base_dir / "requirements.json",
        }
        for path in self._legacy_files.values():
            if not path.exists():
                path.write_text("[]", encoding="utf-8")
        self._init_schema()
        self._migrate_legacy_json_if_needed()

    def list(
        self,
        collection: str,
        *,
        include_deleted: bool = False,
        page: int | None = None,
        page_size: int | None = None,
        sort_by: str = "created_at",
        sort_order: str = "asc",
    ) -> list[dict[str, Any]]:
        return self.list_with_meta(
            collection,
            include_deleted=include_deleted,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )["items"]

    def list_with_meta(
        self,
        collection: str,
        *,
        include_deleted: bool = False,
        page: int | None = None,
        page_size: int | None = None,
        sort_by: str = "created_at",
        sort_order: str = "asc",
    ) -> dict[str, Any]:
        self._validate_collection(collection)
        page_value = max(int(page or 1), 1)
        page_size_value = max(min(int(page_size or 50), 200), 1)
        sort_column = "updated_at" if sort_by == "updated_at" else "created_at"
        sort_direction = "DESC" if sort_order.lower() == "desc" else "ASC"

        where_clause = "WHERE collection = ?"
        params: list[Any] = [collection]
        if not include_deleted:
            where_clause += " AND deleted_at IS NULL"

        total_row = self._db.fetchone(
            f"SELECT COUNT(1) AS c FROM entities {where_clause}",
            tuple(params),
        )
        total = int(total_row["c"]) if total_row else 0
        offset = (page_value - 1) * page_size_value

        rows = self._db.fetchall(
            """
            SELECT payload
            FROM entities
            """
            + where_clause
            + f"""
            ORDER BY {sort_column} {sort_direction}, id ASC
            LIMIT ? OFFSET ?
            """,
            tuple([*params, page_size_value, offset]),
        )
        items = [json.loads(row["payload"]) for row in rows]
        return {
            "items": items,
            "total": total,
            "page": page_value,
            "pageSize": page_size_value,
            "hasNext": offset + len(items) < total,
        }

    def search_cases_with_meta(
        self,
        *,
        project_id: str | None = None,
        spec_id: str | None = None,
        kind: str | None = None,
        q: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        self._validate_collection("cases")
        page_value = max(int(page or 1), 1)
        page_size_value = max(min(int(page_size or 20), 200), 1)
        sort_column = "created_at" if sort_by in {"created_at", "createdAt"} else "updated_at"
        sort_direction = "DESC" if sort_order.lower() == "desc" else "ASC"
        normalized_q = (q or "").strip().lower()

        where_parts = ["collection = ?", "deleted_at IS NULL"]
        params: list[Any] = ["cases"]
        project_expr = self._json_text_expr("projectId")
        spec_expr = self._json_text_expr("specId")
        kind_expr = self._json_text_expr("kind")

        if project_id:
            where_parts.append(f"{project_expr} = ?")
            params.append(project_id)
        if spec_id:
            where_parts.append(f"{spec_expr} = ?")
            params.append(spec_id)
        if kind:
            where_parts.append(f"{kind_expr} = ?")
            params.append(kind)
        if normalized_q:
            where_parts.append(f"{self._case_search_text_expr()} LIKE ?")
            params.append(f"%{normalized_q}%")

        where_clause = "WHERE " + " AND ".join(where_parts)
        total_row = self._db.fetchone(
            f"SELECT COUNT(1) AS c FROM entities {where_clause}",
            tuple(params),
        )
        total = int(total_row["c"]) if total_row else 0
        offset = (page_value - 1) * page_size_value
        rows = self._db.fetchall(
            """
            SELECT payload
            FROM entities
            """
            + where_clause
            + f"""
            ORDER BY {sort_column} {sort_direction}, id ASC
            LIMIT ? OFFSET ?
            """,
            tuple([*params, page_size_value, offset]),
        )
        items = [json.loads(row["payload"]) for row in rows]
        return {
            "items": items,
            "total": total,
            "page": page_value,
            "pageSize": page_size_value,
            "hasNext": offset + len(items) < total,
        }

    def search_projects_with_meta(
        self,
        *,
        q: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        self._validate_collection("projects")
        page_value = max(int(page or 1), 1)
        page_size_value = max(min(int(page_size or 20), 200), 1)
        sort_column = "created_at" if sort_by in {"created_at", "createdAt"} else "updated_at"
        sort_direction = "DESC" if sort_order.lower() == "desc" else "ASC"
        normalized_q = (q or "").strip().lower()

        where_parts = ["collection = ?", "deleted_at IS NULL"]
        params: list[Any] = ["projects"]
        if normalized_q:
            where_parts.append(f"{self._project_search_text_expr()} LIKE ?")
            params.append(f"%{normalized_q}%")

        where_clause = "WHERE " + " AND ".join(where_parts)
        total_row = self._db.fetchone(
            f"SELECT COUNT(1) AS c FROM entities {where_clause}",
            tuple(params),
        )
        total = int(total_row["c"]) if total_row else 0
        offset = (page_value - 1) * page_size_value
        rows = self._db.fetchall(
            """
            SELECT payload
            FROM entities
            """
            + where_clause
            + f"""
            ORDER BY {sort_column} {sort_direction}, id ASC
            LIMIT ? OFFSET ?
            """,
            tuple([*params, page_size_value, offset]),
        )
        items = [json.loads(row["payload"]) for row in rows]
        return {
            "items": items,
            "total": total,
            "page": page_value,
            "pageSize": page_size_value,
            "hasNext": offset + len(items) < total,
        }

    def list_by_json_field(
        self,
        collection: str,
        *,
        field_name: str,
        field_value: str,
        sort_by: str = "created_at",
        sort_order: str = "asc",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_collection(collection)
        sort_column = "updated_at" if sort_by == "updated_at" else "created_at"
        sort_direction = "DESC" if sort_order.lower() == "desc" else "ASC"
        limit_clause = f"LIMIT {limit}" if limit else ""
        rows = self._db.fetchall(
            """
            SELECT payload
            FROM entities
            WHERE collection = ? AND deleted_at IS NULL
              AND """
            + self._json_text_expr(field_name)
            + f""" = ?
            ORDER BY {sort_column} {sort_direction}, id ASC
            {limit_clause}
            """,
            (collection, field_value),
        )
        return [json.loads(row["payload"]) for row in rows]

    def list_all(
        self,
        collection: str,
        *,
        sort_by: str = "created_at",
        sort_order: str = "asc",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_collection(collection)
        sort_column = "updated_at" if sort_by == "updated_at" else "created_at"
        sort_direction = "DESC" if sort_order.lower() == "desc" else "ASC"
        limit_clause = f"LIMIT {limit}" if limit else ""
        rows = self._db.fetchall(
            f"""
            SELECT payload
            FROM entities
            WHERE collection = ? AND deleted_at IS NULL
            ORDER BY {sort_column} {sort_direction}, id ASC
            {limit_clause}
            """,
            (collection,),
        )
        return [json.loads(row["payload"]) for row in rows]

    def list_deleted(
        self,
        collection: str,
        *,
        page: int | None = None,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        self._validate_collection(collection)
        page_value = max(int(page or 1), 1)
        page_size_value = max(min(int(page_size or 50), 200), 1)
        total_row = self._db.fetchone(
            """
            SELECT COUNT(1) AS c
            FROM entities
            WHERE collection = ? AND deleted_at IS NOT NULL
            """,
            (collection,),
        )
        total = int(total_row["c"]) if total_row else 0
        offset = (page_value - 1) * page_size_value
        rows = self._db.fetchall(
            """
            SELECT payload, deleted_at
            FROM entities
            WHERE collection = ? AND deleted_at IS NOT NULL
            ORDER BY deleted_at DESC, id ASC
            LIMIT ? OFFSET ?
            """,
            (collection, page_size_value, offset),
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload"])
            payload["deletedAt"] = row.get("deleted_at")
            items.append(payload)
        return {
            "items": items,
            "total": total,
            "page": page_value,
            "pageSize": page_size_value,
            "hasNext": offset + len(items) < total,
        }

    def get(
        self,
        collection: str,
        entity_id: str,
        *,
        include_deleted: bool = False,
    ) -> dict[str, Any] | None:
        self._validate_collection(collection)
        where_clause = "collection = ? AND id = ?"
        params: list[Any] = [collection, entity_id]
        if not include_deleted:
            where_clause += " AND deleted_at IS NULL"
        row = self._db.fetchone(
            """
            SELECT payload
            FROM entities
            WHERE """
            + where_clause,
            tuple(params),
        )
        return json.loads(row["payload"]) if row else None

    def get_deleted_at(self, collection: str, entity_id: str) -> str | None:
        self._validate_collection(collection)
        row = self._db.fetchone(
            """
            SELECT deleted_at
            FROM entities
            WHERE collection = ? AND id = ?
            """,
            (collection, entity_id),
        )
        if not row:
            return None
        deleted_at = row.get("deleted_at")
        return str(deleted_at) if isinstance(deleted_at, str) and deleted_at else None

    def insert(self, collection: str, entity: dict[str, Any]) -> dict[str, Any]:
        self._validate_collection(collection)
        entity_id = entity.get("id")
        if not entity_id:
            raise ValueError("entity.id is required")

        with self._lock:
            now = _utc_now()
            created_at = _extract_created_time(entity, now)
            payload = json.dumps(entity, ensure_ascii=False)
            self._db.execute(
                """
                INSERT INTO entities (collection, id, payload, created_at, updated_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (collection, entity_id, payload, created_at, now, None),
            )
        return entity

    def update(self, collection: str, entity_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        self._validate_collection(collection)
        with self._lock:
            row = self._db.fetchone(
                """
                SELECT payload, created_at
                FROM entities
                WHERE collection = ? AND id = ? AND deleted_at IS NULL
                """,
                (collection, entity_id),
            )
            if not row:
                raise KeyError(f"{collection}:{entity_id} not found")

            current = json.loads(row["payload"])
            updated = {**current, **patch}
            self._db.execute(
                """
                UPDATE entities
                SET payload = ?, updated_at = ?
                WHERE collection = ? AND id = ?
                """,
                (
                    json.dumps(updated, ensure_ascii=False),
                    _utc_now(),
                    collection,
                    entity_id,
                ),
            )
            return updated

    def filter_by(self, collection: str, key: str, value: str) -> list[dict[str, Any]]:
        return [item for item in self.list(collection) if item.get(key) == value]

    def soft_delete(self, collection: str, entity_id: str) -> bool:
        self._validate_collection(collection)
        row = self._db.fetchone(
            """
            SELECT id
            FROM entities
            WHERE collection = ? AND id = ? AND deleted_at IS NULL
            """,
            (collection, entity_id),
        )
        if not row:
            return False
        self._db.execute(
            """
            UPDATE entities
            SET deleted_at = ?, updated_at = ?
            WHERE collection = ? AND id = ?
            """,
            (_utc_now(), _utc_now(), collection, entity_id),
        )
        return True

    def restore(self, collection: str, entity_id: str) -> bool:
        self._validate_collection(collection)
        row = self._db.fetchone(
            """
            SELECT id
            FROM entities
            WHERE collection = ? AND id = ? AND deleted_at IS NOT NULL
            """,
            (collection, entity_id),
        )
        if not row:
            return False
        self._db.execute(
            """
            UPDATE entities
            SET deleted_at = NULL, updated_at = ?
            WHERE collection = ? AND id = ?
            """,
            (_utc_now(), collection, entity_id),
        )
        return True

    def _init_schema(self) -> None:
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS entities (
                collection TEXT NOT NULL,
                id TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT,
                PRIMARY KEY (collection, id)
            )
            """
        )
        self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_entities_collection_created
            ON entities(collection, created_at)
            """
        )
        self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_entities_collection_deleted_updated
            ON entities(collection, deleted_at, updated_at DESC, id ASC)
            """
        )
        self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_entities_collection_deleted_created
            ON entities(collection, deleted_at, created_at DESC, id ASC)
            """
        )
        if self._db.dialect == "postgres":
            self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_entities_cases_project_kind_updated
                ON entities(
                    collection,
                    deleted_at,
                    ((payload::jsonb ->> 'projectId')),
                    ((payload::jsonb ->> 'kind')),
                    updated_at DESC,
                    id ASC
                )
                """
            )
            self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_entities_cases_spec_updated
                ON entities(
                    collection,
                    deleted_at,
                    ((payload::jsonb ->> 'specId')),
                    updated_at DESC,
                    id ASC
                )
                """
            )
            self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_entities_cases_kind_updated
                ON entities(
                    collection,
                    deleted_at,
                    ((payload::jsonb ->> 'kind')),
                    updated_at DESC,
                    id ASC
                )
                """
            )
            self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_entities_specs_project_created
                ON entities(
                    collection,
                    deleted_at,
                    ((payload::jsonb ->> 'projectId')),
                    created_at ASC,
                    id ASC
                )
                """
            )
        else:
            self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_entities_cases_project_kind_updated
                ON entities(
                    collection,
                    deleted_at,
                    json_extract(payload, '$.projectId'),
                    json_extract(payload, '$.kind'),
                    updated_at DESC,
                    id ASC
                )
                """
            )
            self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_entities_cases_spec_updated
                ON entities(
                    collection,
                    deleted_at,
                    json_extract(payload, '$.specId'),
                    updated_at DESC,
                    id ASC
                )
                """
            )
            self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_entities_cases_kind_updated
                ON entities(
                    collection,
                    deleted_at,
                    json_extract(payload, '$.kind'),
                    updated_at DESC,
                    id ASC
                )
                """
            )
            self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_entities_specs_project_created
                ON entities(
                    collection,
                    deleted_at,
                    json_extract(payload, '$.projectId'),
                    created_at ASC,
                    id ASC
                )
                """
            )
        # Legacy compatibility: entities table created before deleted_at support.
        try:
            self._db.fetchone("SELECT deleted_at FROM entities LIMIT 1")
        except Exception:
            try:
                self._db.execute("ALTER TABLE entities ADD COLUMN deleted_at TEXT")
            except Exception:
                pass

    def _migrate_legacy_json_if_needed(self) -> None:
        with self._lock:
            for collection, file_path in self._legacy_files.items():
                count_row = self._db.fetchone(
                    "SELECT COUNT(1) AS c FROM entities WHERE collection = ?",
                    (collection,),
                )
                count = int(count_row["c"]) if count_row else 0
                if count > 0 or not file_path.exists():
                    continue

                raw_data = json.loads(file_path.read_text(encoding="utf-8"))
                if not isinstance(raw_data, list):
                    continue

                now = _utc_now()
                for item in raw_data:
                    entity_id = item.get("id")
                    if not entity_id:
                        continue
                    exists = self._db.fetchone(
                        "SELECT id FROM entities WHERE collection = ? AND id = ?",
                        (collection, entity_id),
                    )
                    if exists:
                        continue
                    self._db.execute(
                        """
                        INSERT INTO entities (collection, id, payload, created_at, updated_at, deleted_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            collection,
                            entity_id,
                            json.dumps(item, ensure_ascii=False),
                            _extract_created_time(item, now),
                            now,
                            None,
                        ),
                    )

    def _validate_collection(self, collection: str) -> None:
        if collection not in self._collections:
            raise KeyError(f"unsupported collection: {collection}")

    def _json_text_expr(self, field_name: str) -> str:
        if self._db.dialect == "postgres":
            return f"(payload::jsonb ->> '{field_name}')"
        return f"json_extract(payload, '$.{field_name}')"

    def _case_search_text_expr(self) -> str:
        title_expr = self._json_text_expr("title")
        objective_expr = self._json_text_expr("objective")
        steps_expr = self._json_text_expr("steps")
        assertion_hints_expr = self._json_text_expr("assertionHints")
        return (
            "LOWER("
            "COALESCE(id, '') || ' ' || "
            f"COALESCE({title_expr}, '') || ' ' || "
            f"COALESCE({objective_expr}, '') || ' ' || "
            f"COALESCE({steps_expr}, '') || ' ' || "
            f"COALESCE({assertion_hints_expr}, '')"
            ")"
        )

    def _project_search_text_expr(self) -> str:
        name_expr = self._json_text_expr("name")
        description_expr = self._json_text_expr("description")
        return (
            "LOWER("
            f"COALESCE({name_expr}, '') || ' ' || "
            f"COALESCE({description_expr}, '')"
            ")"
        )


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _extract_created_time(entity: dict[str, Any], fallback: str) -> str:
    for key in ("createdAt", "startedAt"):
        value = entity.get(key)
        if isinstance(value, str) and value:
            return value
    return fallback

import json
from typing import Any, List, Optional
from app.database import Database
from app.core.utils import new_id, utc_now

class RequirementRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get_by_id(self, req_id: str, include_deleted: bool = False) -> Optional[dict[str, Any]]:
        query = "SELECT * FROM requirements WHERE id = ?" if self._db.dialect == "sqlite" else "SELECT * FROM requirements WHERE id = %s"
        if not include_deleted:
            query += " AND deleted_at IS NULL"
        
        row = self._db.fetchone(query, (req_id,))
        return dict(row) if row else None

    def exists_same(self, project_id: str, title: str, content: str) -> bool:
        query = """
            SELECT 1 FROM requirements 
            WHERE project_id = ? AND title = ? AND content = ? AND deleted_at IS NULL 
            LIMIT 1
        """ if self._db.dialect == "sqlite" else """
            SELECT 1 FROM requirements 
            WHERE project_id = %s AND title = %s AND content = %s AND deleted_at IS NULL 
            LIMIT 1
        """
        row = self._db.fetchone(query, (project_id, title, content))
        return bool(row)

    def create(self, data: dict[str, Any]) -> str:
        req_id = data.get("id") or new_id("req")
        cols = []
        placeholders = []
        vals = []
        for k, v in data.items():
            cols.append(k)
            placeholders.append("?" if self._db.dialect == "sqlite" else "%s")
            vals.append(v if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False))
        
        query = f"INSERT INTO requirements ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
        self._db.execute(query, tuple(vals))
        return req_id

    def update(self, req_id: str, updates: dict[str, Any]) -> None:
        updates["updated_at"] = utc_now()
        cols = []
        vals = []
        for k, v in updates.items():
            cols.append(f"{k} = ?" if self._db.dialect == "sqlite" else f"{k} = %s")
            vals.append(v if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False))
        
        vals.append(req_id)
        query = f"UPDATE requirements SET {', '.join(cols)} WHERE id = ?" if self._db.dialect == "sqlite" else f"UPDATE requirements SET {', '.join(cols)} WHERE id = %s"
        self._db.execute(query, tuple(vals))

    def batch_delete(self, ids: list[str], *, hard: bool = False) -> int:
        if not ids:
            return 0
        placeholders = ",".join(["?"] * len(ids)) if self._db.dialect == "sqlite" else ",".join(["%s"] * len(ids))
        if hard:
            query = f"DELETE FROM requirements WHERE id IN ({placeholders})"
            return self._db.execute(query, tuple(ids))
        else:
            now = utc_now()
            query = f"UPDATE requirements SET deleted_at = ?, updated_at = ? WHERE id IN ({placeholders}) AND deleted_at IS NULL"
            return self._db.execute(query, tuple([now, now, *ids]))

    def batch_restore(self, ids: list[str]) -> int:
        if not ids:
            return 0
        now = utc_now()
        placeholders = ",".join(["?"] * len(ids)) if self._db.dialect == "sqlite" else ",".join(["%s"] * len(ids))
        query = f"UPDATE requirements SET deleted_at = NULL, updated_at = ? WHERE id IN ({placeholders}) AND deleted_at IS NOT NULL"
        return self._db.execute(query, tuple([now, *ids]))

    def soft_delete(self, req_id: str) -> bool:
        query = "UPDATE requirements SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL"
        if self._db.dialect != "sqlite":
            query = "UPDATE requirements SET deleted_at = %s, updated_at = %s WHERE id = %s AND deleted_at IS NULL"
        rows_affected = self._db.execute(query, (utc_now(), utc_now(), req_id))
        return rows_affected > 0

    def hard_delete(self, req_id: str) -> bool:
        query = "DELETE FROM requirements WHERE id = ?"
        if self._db.dialect != "sqlite":
            query = "DELETE FROM requirements WHERE id = %s"
        rows_affected = self._db.execute(query, (req_id,))
        return rows_affected > 0

    def restore(self, req_id: str) -> bool:
        query = "UPDATE requirements SET deleted_at = NULL, updated_at = ? WHERE id = ? AND deleted_at IS NOT NULL"
        if self._db.dialect == "sqlite":
            query = "UPDATE requirements SET deleted_at = NULL, updated_at = ? WHERE id = ? AND deleted_at IS NOT NULL"
        else:
            query = "UPDATE requirements SET deleted_at = NULL, updated_at = %s WHERE id = %s AND deleted_at IS NOT NULL"
        rows_affected = self._db.execute(query, (utc_now(), req_id))
        return rows_affected > 0

    def get_latest_analysis_version(self, requirement_id: str) -> Optional[dict[str, Any]]:
        query = """
            SELECT * FROM requirement_analysis_versions 
            WHERE requirement_id = ? 
            ORDER BY version DESC LIMIT 1
        """ if self._db.dialect == "sqlite" else """
            SELECT * FROM requirement_analysis_versions 
            WHERE requirement_id = %s 
            ORDER BY version DESC LIMIT 1
        """
        row = self._db.fetchone(query, (requirement_id,))
        return dict(row) if row else None

    def create_analysis_version(self, data: dict[str, Any]) -> str:
        ver_id = data.get("id") or new_id("ran")
        cols = []
        placeholders = []
        vals = []
        for k, v in data.items():
            cols.append(k)
            placeholders.append("?" if self._db.dialect == "sqlite" else "%s")
            vals.append(v if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False))
        
        query = f"INSERT INTO requirement_analysis_versions ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
        self._db.execute(query, tuple(vals))
        return ver_id

    def search(
        self, 
        *, 
        org_ids: list[str] | None = None, 
        project_id: str | None = None, 
        q: str | None = None, 
        status: str | None = None, 
        page: int = 1, 
        page_size: int = 50, 
        sort_by: str = "created_at", 
        sort_order: str = "DESC",
        include_deleted: bool = False,
        only_deleted: bool = False
    ) -> tuple[List[dict[str, Any]], int]:
        conditions = []
        params = []

        if only_deleted:
            conditions.append("deleted_at IS NOT NULL")
        elif not include_deleted:
            conditions.append("deleted_at IS NULL")

        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)
        
        if org_ids:
            placeholders = ",".join(["?"] * len(org_ids))
            conditions.append(f"org_id IN ({placeholders})")
            params.extend(org_ids)

        if status:
            conditions.append("status = ?")
            params.append(status)

        if q:
            like_text = f"%{q.lower()}%"
            if self._db.dialect == "postgres":
                conditions.append(
                    "("
                    "to_tsvector('simple', COALESCE(title,'') || ' ' || COALESCE(content,'') || ' ' || COALESCE(tags_json,'')) "
                    "@@ plainto_tsquery('simple', ?)"
                    " OR LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR LOWER(tags_json) LIKE ?"
                    ")"
                )
                params.extend([q.lower(), like_text, like_text, like_text])
            else:
                conditions.append("(LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR LOWER(tags_json) LIKE ?)")
                params.extend([like_text, like_text, like_text])

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        
        # Count
        count_row = self._db.fetchone(f"SELECT COUNT(*) as c FROM requirements {where_clause}", tuple(params))
        total = count_row["c"] if count_row else 0

        # Map camelCase to snake_case for database columns
        column_mapping = {
            "createdAt": "created_at",
            "updatedAt": "updated_at",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
        db_sort_by = column_mapping.get(sort_by, sort_by)

        # Data
        offset = (page - 1) * page_size
        query = f"SELECT * FROM requirements {where_clause} ORDER BY {db_sort_by} {sort_order}, id ASC LIMIT ? OFFSET ?"
        rows = self._db.fetchall(query, tuple(params + [page_size, offset]))
        
        return [dict(r) for r in rows], total

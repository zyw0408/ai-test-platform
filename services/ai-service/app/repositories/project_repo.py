from typing import Any, List, Optional
from app.database import Database
from app.core.utils import new_id, utc_now

class ProjectRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list_by_orgs(self, org_ids: List[str]) -> List[dict[str, Any]]:
        if not org_ids:
            return []
        placeholders = ",".join(["?"] * len(org_ids)) if self._db.dialect == "sqlite" else ",".join(["%s"] * len(org_ids))
        query = f"SELECT * FROM projects WHERE org_id IN ({placeholders}) AND deleted_at IS NULL ORDER BY created_at DESC"
        return [dict(r) for r in self._db.fetchall(query, tuple(org_ids))]

    def search(self, *, org_ids: List[str], query_text: Optional[str] = None, 
               limit: int = 20, offset: int = 0, 
               sort_by: str = "created_at", sort_order: str = "desc") -> dict[str, Any]:
        where_parts = ["deleted_at IS NULL", f"org_id IN ({','.join(['?']*len(org_ids)) if self._db.dialect == 'sqlite' else ','.join(['%s']*len(org_ids))})"]
        params = [*org_ids]
        
        if query_text:
            where_parts.append("(name LIKE ? OR description LIKE ?)" if self._db.dialect == "sqlite" else "(name ILIKE %s OR description ILIKE %s)")
            params.extend([f"%{query_text}%", f"%{query_text}%"])
            
        where_clause = " AND ".join(where_parts)
        order_col = "updated_at" if sort_by in {"updated_at", "updatedAt"} else "created_at"
        order_dir = "DESC" if sort_order.lower() == "desc" else "ASC"
        
        query = f"SELECT * FROM projects WHERE {where_clause} ORDER BY {order_col} {order_dir} LIMIT ? OFFSET ?"
        rows = self._db.fetchall(query, tuple([*params, limit, offset]))
        
        count_query = f"SELECT COUNT(*) as total FROM projects WHERE {where_clause}"
        count_row = self._db.fetchone(count_query, tuple(params))
        total = count_row["total"] if count_row else 0
        
        return {"items": [dict(r) for r in rows], "total": total}

    def get_by_id(self, project_id: str) -> Optional[dict[str, Any]]:
        row = self._db.fetchone(
            "SELECT * FROM projects WHERE id = ? AND deleted_at IS NULL" if self._db.dialect == "sqlite" else "SELECT * FROM projects WHERE id = %s AND deleted_at IS NULL",
            (project_id,)
        )
        return dict(row) if row else None

    def exists_by_name(self, org_id: str, name: str) -> bool:
        query = "SELECT 1 FROM projects WHERE org_id = ? AND name = ? AND deleted_at IS NULL LIMIT 1" if self._db.dialect == "sqlite" else "SELECT 1 FROM projects WHERE org_id = %s AND name = %s AND deleted_at IS NULL LIMIT 1"
        row = self._db.fetchone(query, (org_id, name))
        return bool(row)

    def create(self, org_id: str, name: str, description: str = "") -> dict[str, Any]:
        now = utc_now()
        pid = new_id("proj")
        if self._db.dialect == "sqlite":
            self._db.execute(
                "INSERT INTO projects (id, org_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (pid, org_id, name, description, now, now)
            )
        else:
            self._db.execute(
                "INSERT INTO projects (id, org_id, name, description, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (pid, org_id, name, description, now, now)
            )
        return self.get_by_id(pid) or {"id": pid}

    def update(self, project_id: str, data: dict[str, Any]) -> None:
        data["updated_at"] = utc_now()
        cols = [f"{k} = ?" for k in data.keys()] if self._db.dialect == "sqlite" else [f"{k} = %s" for k in data.keys()]
        vals = list(data.values())
        vals.append(project_id)
        query = f"UPDATE projects SET {', '.join(cols)} WHERE id = ? AND deleted_at IS NULL" if self._db.dialect == "sqlite" else f"UPDATE projects SET {', '.join(cols)} WHERE id = %s AND deleted_at IS NULL"
        self._db.execute(query, tuple(vals))

    def _json_text_expr(self, field_name: str) -> str:
        if self._db.dialect == "postgres":
            return f"(payload::jsonb ->> '{field_name}')"
        return f"json_extract(payload, '$.{field_name}')"

    def delete(self, project_id: str) -> None:
        now = utc_now()
        placeholder = "?" if self._db.dialect == "sqlite" else "%s"

        # 1) 软删除项目及其核心业务数据（需求/用例/规格/接口集合）
        self._db.execute(
            "UPDATE projects SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL"
            if self._db.dialect == "sqlite"
            else "UPDATE projects SET deleted_at = %s, updated_at = %s WHERE id = %s AND deleted_at IS NULL",
            (now, now, project_id),
        )
        self._db.execute(
            "UPDATE requirements SET deleted_at = ?, updated_at = ? WHERE project_id = ? AND deleted_at IS NULL"
            if self._db.dialect == "sqlite"
            else "UPDATE requirements SET deleted_at = %s, updated_at = %s WHERE project_id = %s AND deleted_at IS NULL",
            (now, now, project_id),
        )
        self._db.execute(
            "UPDATE cases SET deleted_at = ?, updated_at = ? WHERE project_id = ? AND deleted_at IS NULL"
            if self._db.dialect == "sqlite"
            else "UPDATE cases SET deleted_at = %s, updated_at = %s WHERE project_id = %s AND deleted_at IS NULL",
            (now, now, project_id),
        )
        self._db.execute(
            "UPDATE source_specs SET deleted_at = ?, updated_at = ? WHERE project_id = ? AND deleted_at IS NULL"
            if self._db.dialect == "sqlite"
            else "UPDATE source_specs SET deleted_at = %s, updated_at = %s WHERE project_id = %s AND deleted_at IS NULL",
            (now, now, project_id),
        )
        self._db.execute(
            "UPDATE api_collections SET deleted_at = ?, updated_at = ? WHERE project_id = ? AND deleted_at IS NULL"
            if self._db.dialect == "sqlite"
            else "UPDATE api_collections SET deleted_at = %s, updated_at = %s WHERE project_id = %s AND deleted_at IS NULL",
            (now, now, project_id),
        )

        # 2) 按集合级联软删接口与环境，并清理接口运行记录
        collection_rows = self._db.fetchall(
            "SELECT id FROM api_collections WHERE project_id = ?"
            if self._db.dialect == "sqlite"
            else "SELECT id FROM api_collections WHERE project_id = %s",
            (project_id,),
        )
        collection_ids = [str(row.get("id") or "").strip() for row in collection_rows if str(row.get("id") or "").strip()]
        if collection_ids:
            id_placeholders = ",".join(["?"] * len(collection_ids)) if self._db.dialect == "sqlite" else ",".join(["%s"] * len(collection_ids))
            self._db.execute(
                f"UPDATE api_requests SET deleted_at = {placeholder}, updated_at = {placeholder} WHERE collection_id IN ({id_placeholders}) AND deleted_at IS NULL",
                tuple([now, now, *collection_ids]),
            )
            self._db.execute(
                f"UPDATE api_environments SET deleted_at = {placeholder}, updated_at = {placeholder} WHERE collection_id IN ({id_placeholders}) AND deleted_at IS NULL",
                tuple([now, now, *collection_ids]),
            )
            self._db.execute(
                f"DELETE FROM api_request_runs WHERE collection_id IN ({id_placeholders})",
                tuple(collection_ids),
            )

        # 3) 清理安全与向量相关数据
        self._db.execute(
            "DELETE FROM security_findings WHERE project_id = ?"
            if self._db.dialect == "sqlite"
            else "DELETE FROM security_findings WHERE project_id = %s",
            (project_id,),
        )
        self._db.execute(
            "DELETE FROM vector_documents WHERE project_id = ?"
            if self._db.dialect == "sqlite"
            else "DELETE FROM vector_documents WHERE project_id = %s",
            (project_id,),
        )
        self._db.execute(
            "DELETE FROM audit_logs WHERE target_type = ? AND target_id = ?"
            if self._db.dialect == "sqlite"
            else "DELETE FROM audit_logs WHERE target_type = %s AND target_id = %s",
            ("project", project_id),
        )

        # 4) 软删除 JsonStore 实体（运行记录/报告相关）
        project_expr = self._json_text_expr("projectId")
        self._db.execute(
            f"""
            UPDATE entities
            SET deleted_at = {placeholder}, updated_at = {placeholder}
            WHERE collection IN ('projects', 'specs', 'requirements', 'cases', 'runs', 'performance_runs')
              AND deleted_at IS NULL
              AND {project_expr} = {placeholder}
            """,
            (now, now, project_id),
        )

        run_rows = self._db.fetchall(
            f"""
            SELECT id
            FROM entities
            WHERE collection = 'runs'
              AND {project_expr} = {placeholder}
            """,
            (project_id,),
        )
        run_ids = [str(row.get("id") or "").strip() for row in run_rows if str(row.get("id") or "").strip()]
        if run_ids:
            run_placeholders = ",".join(["?"] * len(run_ids)) if self._db.dialect == "sqlite" else ",".join(["%s"] * len(run_ids))
            run_id_expr = self._json_text_expr("runId")
            self._db.execute(
                f"""
                UPDATE entities
                SET deleted_at = {placeholder}, updated_at = {placeholder}
                WHERE collection = 'artifacts'
                  AND deleted_at IS NULL
                  AND {run_id_expr} IN ({run_placeholders})
                """,
                tuple([now, now, *run_ids]),
            )

    def list_deleted(self, *, org_ids: List[str], limit: int = 20, offset: int = 0) -> dict[str, Any]:
        if not org_ids:
            return {"items": [], "total": 0}
        placeholders = ",".join(["?"] * len(org_ids)) if self._db.dialect == "sqlite" else ",".join(["%s"] * len(org_ids))
        query = f"SELECT * FROM projects WHERE org_id IN ({placeholders}) AND deleted_at IS NOT NULL ORDER BY deleted_at DESC LIMIT ? OFFSET ?"
        rows = self._db.fetchall(query, tuple([*org_ids, limit, offset]))
        
        count_query = f"SELECT COUNT(*) as total FROM projects WHERE org_id IN ({placeholders}) AND deleted_at IS NOT NULL"
        count_row = self._db.fetchone(count_query, tuple(org_ids))
        total = count_row["total"] if count_row else 0
        
        return {"items": [dict(r) for r in rows], "total": total}

    def restore(self, project_id: str) -> Optional[dict[str, Any]]:
        self._db.execute(
            "UPDATE projects SET deleted_at = NULL, updated_at = ? WHERE id = ? AND deleted_at IS NOT NULL" if self._db.dialect == "sqlite" else "UPDATE projects SET deleted_at = NULL, updated_at = %s WHERE id = %s AND deleted_at IS NOT NULL",
            (utc_now(), project_id)
        )
        return self.get_by_id(project_id)

    def purge_deleted(self, project_id: str) -> bool:
        row = self._db.fetchone(
            "SELECT id FROM projects WHERE id = ? AND deleted_at IS NOT NULL"
            if self._db.dialect == "sqlite"
            else "SELECT id FROM projects WHERE id = %s AND deleted_at IS NOT NULL",
            (project_id,),
        )
        if not row:
            return False

        placeholder = "?" if self._db.dialect == "sqlite" else "%s"
        project_expr = self._json_text_expr("projectId")
        run_id_expr = self._json_text_expr("runId")

        collection_rows = self._db.fetchall(
            "SELECT id FROM api_collections WHERE project_id = ?"
            if self._db.dialect == "sqlite"
            else "SELECT id FROM api_collections WHERE project_id = %s",
            (project_id,),
        )
        collection_ids = [str(item.get("id") or "").strip() for item in collection_rows if str(item.get("id") or "").strip()]
        if collection_ids:
            c_placeholders = ",".join(["?"] * len(collection_ids)) if self._db.dialect == "sqlite" else ",".join(["%s"] * len(collection_ids))
            self._db.execute(
                f"DELETE FROM api_requests WHERE collection_id IN ({c_placeholders})",
                tuple(collection_ids),
            )
            self._db.execute(
                f"DELETE FROM api_environments WHERE collection_id IN ({c_placeholders})",
                tuple(collection_ids),
            )
            self._db.execute(
                f"DELETE FROM api_request_runs WHERE collection_id IN ({c_placeholders})",
                tuple(collection_ids),
            )
            self._db.execute(
                f"DELETE FROM api_collections WHERE id IN ({c_placeholders})",
                tuple(collection_ids),
            )

        self._db.execute(
            "DELETE FROM requirements WHERE project_id = ?"
            if self._db.dialect == "sqlite"
            else "DELETE FROM requirements WHERE project_id = %s",
            (project_id,),
        )
        self._db.execute(
            "DELETE FROM cases WHERE project_id = ?"
            if self._db.dialect == "sqlite"
            else "DELETE FROM cases WHERE project_id = %s",
            (project_id,),
        )
        self._db.execute(
            "DELETE FROM source_specs WHERE project_id = ?"
            if self._db.dialect == "sqlite"
            else "DELETE FROM source_specs WHERE project_id = %s",
            (project_id,),
        )
        self._db.execute(
            "DELETE FROM security_findings WHERE project_id = ?"
            if self._db.dialect == "sqlite"
            else "DELETE FROM security_findings WHERE project_id = %s",
            (project_id,),
        )
        self._db.execute(
            "DELETE FROM vector_documents WHERE project_id = ?"
            if self._db.dialect == "sqlite"
            else "DELETE FROM vector_documents WHERE project_id = %s",
            (project_id,),
        )
        self._db.execute(
            "DELETE FROM audit_logs WHERE target_type = ? AND target_id = ?"
            if self._db.dialect == "sqlite"
            else "DELETE FROM audit_logs WHERE target_type = %s AND target_id = %s",
            ("project", project_id),
        )

        run_rows = self._db.fetchall(
            f"""
            SELECT id FROM entities
            WHERE collection = 'runs' AND {project_expr} = {placeholder}
            """,
            (project_id,),
        )
        run_ids = [str(item.get("id") or "").strip() for item in run_rows if str(item.get("id") or "").strip()]
        if run_ids:
            r_placeholders = ",".join(["?"] * len(run_ids)) if self._db.dialect == "sqlite" else ",".join(["%s"] * len(run_ids))
            self._db.execute(
                f"DELETE FROM entities WHERE collection = 'artifacts' AND {run_id_expr} IN ({r_placeholders})",
                tuple(run_ids),
            )

        self._db.execute(
            f"""
            DELETE FROM entities
            WHERE collection IN ('projects', 'specs', 'requirements', 'cases', 'runs', 'performance_runs')
              AND {project_expr} = {placeholder}
            """,
            (project_id,),
        )
        # projects 集合本身没有 projectId 字段，按 id 再清理一遍
        self._db.execute(
            "DELETE FROM entities WHERE collection = 'projects' AND id = ?"
            if self._db.dialect == "sqlite"
            else "DELETE FROM entities WHERE collection = 'projects' AND id = %s",
            (project_id,),
        )
        self._db.execute(
            "DELETE FROM projects WHERE id = ?"
            if self._db.dialect == "sqlite"
            else "DELETE FROM projects WHERE id = %s",
            (project_id,),
        )
        return True

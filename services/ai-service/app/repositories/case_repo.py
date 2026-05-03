import json
from typing import Any, List, Optional
from app.database import Database
from app.models import utc_now, new_id

class TestCaseRepository:
    def __init__(self, db: Database):
        self._db = db

    def search(
        self,
        *,
        project_id: Optional[str] = None,
        spec_id: Optional[str] = None,
        kind: Optional[str] = None,
        q: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        placeholder = "?" if self._db.dialect == "sqlite" else "%s"
        conditions = ["deleted_at IS NULL"]
        params = []

        if project_id:
            conditions.append(f"project_id = {placeholder}")
            params.append(project_id)
        if spec_id:
            conditions.append(f"spec_id = {placeholder}")
            params.append(spec_id)
        if kind:
            conditions.append(f"kind = {placeholder}")
            params.append(kind)
        if q:
            conditions.append(f"(lower(title) LIKE {placeholder} OR lower(objective) LIKE {placeholder})")
            params.append(f"%{q.lower()}%")
            params.append(f"%{q.lower()}%")

        where = f"WHERE {' AND '.join(conditions)}"
        
        # Count total
        total_row = self._db.fetchone(f"SELECT COUNT(1) as c FROM cases {where}", tuple(params))
        total = total_row["c"] if total_row else 0

        # Data
        valid_sort_cols = {"created_at", "updated_at", "title", "id"}
        sort_col = sort_by if sort_by in valid_sort_cols else "created_at"
        direction = "DESC" if sort_order.lower() == "desc" else "ASC"
        
        offset = (page - 1) * page_size
        if self._db.dialect == "sqlite":
            rows = self._db.fetchall(
                f"""
                SELECT * FROM cases
                {where}
                ORDER BY {sort_col} {direction}, id ASC
                LIMIT ? OFFSET ?
                """,
                tuple([*params, page_size, offset])
            )
        else:
            rows = self._db.fetchall(
                f"""
                SELECT * FROM cases
                {where}
                ORDER BY {sort_col} {direction}, id ASC
                LIMIT %s OFFSET %s
                """,
                tuple([*params, page_size, offset])
            )

        return {
            "items": rows,
            "total": total,
            "page": page,
            "pageSize": page_size,
            "hasNext": offset + len(rows) < total
        }

    def get_by_id(self, case_id: str, include_deleted: bool = False) -> Optional[dict[str, Any]]:
        if self._db.dialect == "sqlite":
            query = "SELECT * FROM cases WHERE id = ?" if include_deleted else "SELECT * FROM cases WHERE id = ? AND deleted_at IS NULL"
        else:
            query = "SELECT * FROM cases WHERE id = %s" if include_deleted else "SELECT * FROM cases WHERE id = %s AND deleted_at IS NULL"
        return self._db.fetchone(query, (case_id,))

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        case_id = data.get("id") or new_id("case")
        now = utc_now()
        
        if self._db.dialect == "sqlite":
            self._db.execute(
                """
                INSERT INTO cases (
                    id, org_id, project_id, spec_id, requirement_id, kind, title, objective, 
                    preconditions, steps_json, assertion_hints_json, payload_json, 
                    created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    data.get("orgId") or data.get("org_id", "DEFAULT_ORG"),
                    data.get("projectId"),
                    data.get("specId"),
                    data.get("requirementId"),
                    data.get("kind", "manual"),
                    data.get("title"),
                    data.get("objective") or "",
                    data.get("preconditions") or "",
                    json.dumps(data.get("steps") or data.get("stepsJson") or [], ensure_ascii=False),
                    json.dumps(data.get("assertionHints") or data.get("assertionHintsJson") or [], ensure_ascii=False),
                    json.dumps(data.get("payload") or data.get("payloadJson") or {}, ensure_ascii=False),
                    data.get("createdBy"),
                    now,
                    now
                )
            )
        else:
            self._db.execute(
                """
                INSERT INTO cases (
                    id, org_id, project_id, spec_id, requirement_id, kind, title, objective, 
                    preconditions, steps_json, assertion_hints_json, payload_json, 
                    created_by, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    case_id,
                    data.get("orgId") or data.get("org_id", "DEFAULT_ORG"),
                    data.get("projectId"),
                    data.get("specId"),
                    data.get("requirementId"),
                    data.get("kind", "manual"),
                    data.get("title"),
                    data.get("objective") or "",
                    data.get("preconditions") or "",
                    json.dumps(data.get("steps") or data.get("stepsJson") or [], ensure_ascii=False),
                    json.dumps(data.get("assertionHints") or data.get("assertionHintsJson") or [], ensure_ascii=False),
                    json.dumps(data.get("payload") or data.get("payloadJson") or {}, ensure_ascii=False),
                    data.get("createdBy"),
                    now,
                    now
                )
            )
        return self.get_by_id(case_id)

    def update(self, case_id: str, updates: dict[str, Any]) -> bool:
        fields = []
        params = []
        
        mapping = {
            "projectId": "project_id",
            "specId": "spec_id",
            "requirementId": "requirement_id",
            "title": "title",
            "objective": "objective",
            "preconditions": "preconditions",
            "kind": "kind",
            "steps": "steps_json",
            "stepsJson": "steps_json",
            "assertionHints": "assertion_hints_json",
            "assertionHintsJson": "assertion_hints_json",
            "payload": "payload_json",
            "payloadJson": "payload_json"
        }
        
        placeholder = "?" if self._db.dialect == "sqlite" else "%s"
        
        for key, col in mapping.items():
            if key in updates:
                val = updates[key]
                if col in ("steps_json", "assertion_hints_json", "payload_json") and not isinstance(val, str):
                    val = json.dumps(val, ensure_ascii=False)
                fields.append(f"{col} = {placeholder}")
                params.append(val)
        
        if not fields:
            return False
            
        fields.append(f"updated_at = {placeholder}")
        params.append(utc_now())
        params.append(case_id)
        
        query = f"UPDATE cases SET {', '.join(fields)} WHERE id = {placeholder} AND deleted_at IS NULL"
        self._db.execute(query, tuple(params))
        return True

    def delete_soft(self, case_id: str) -> bool:
        now = utc_now()
        if self._db.dialect == "sqlite":
            self._db.execute(
                "UPDATE cases SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (now, now, case_id)
            )
        else:
            self._db.execute(
                "UPDATE cases SET deleted_at = %s, updated_at = %s WHERE id = %s AND deleted_at IS NULL",
                (now, now, case_id)
            )
        return True

    def batch_delete_soft(self, case_ids: List[str]) -> int:
        if not case_ids:
            return 0
        now = utc_now()
        placeholders = ",".join(["?"] * len(case_ids)) if self._db.dialect == "sqlite" else ",".join(["%s"] * len(case_ids))
        if self._db.dialect == "sqlite":
            self._db.execute(
                f"UPDATE cases SET deleted_at = ?, updated_at = ? WHERE id IN ({placeholders}) AND deleted_at IS NULL",
                tuple([now, now, *case_ids])
            )
        else:
            self._db.execute(
                f"UPDATE cases SET deleted_at = %s, updated_at = %s WHERE id IN ({placeholders}) AND deleted_at IS NULL",
                tuple([now, now, *case_ids])
            )
        return len(case_ids)

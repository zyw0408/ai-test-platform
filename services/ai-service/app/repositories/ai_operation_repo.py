import json
from typing import Any, Optional
from app.database import Database
from app.core.utils import new_id, utc_now

class AiOperationRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get_by_id(self, operation_id: str) -> Optional[dict[str, Any]]:
        query = "SELECT * FROM ai_operations WHERE id = ?" if self._db.dialect == "sqlite" else "SELECT * FROM ai_operations WHERE id = %s"
        row = self._db.fetchone(query, (operation_id,))
        return dict(row) if row else None

    def create(self, data: dict[str, Any]) -> str:
        op_id = data.get("id") or new_id("aop")
        cols = []
        placeholders = []
        vals = []
        for k, v in data.items():
            cols.append(k)
            placeholders.append("?" if self._db.dialect == "sqlite" else "%s")
            vals.append(v if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False))
        
        query = f"INSERT INTO ai_operations ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
        self._db.execute(query, tuple(vals))
        return op_id

    def update(self, op_id: str, updates: dict[str, Any], increment_attempts: bool = False) -> None:
        updates["updated_at"] = utc_now()
        cols = []
        vals = []
        for k, v in updates.items():
            cols.append(f"{k} = ?" if self._db.dialect == "sqlite" else f"{k} = %s")
            vals.append(v if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False))
        
        if increment_attempts:
            cols.append("attempt_count = attempt_count + 1")
        
        where_placeholder = "?" if self._db.dialect == "sqlite" else "%s"
        query = f"UPDATE ai_operations SET {', '.join(cols)} WHERE id = {where_placeholder}"
        self._db.execute(query, tuple(vals + [op_id]))

    def get_by_id(self, op_id: str) -> Optional[dict[str, Any]]:
        query = "SELECT * FROM ai_operations WHERE id = ?"
        row = self._db.fetchone(query, (op_id,))
        return dict(row) if row else None

    def update(self, op_id: str, updates: dict[str, Any]) -> None:
        updates["updated_at"] = utc_now()
        cols = []
        vals = []
        for k, v in updates.items():
            cols.append(f"{k} = ?" if self._db.dialect == "sqlite" else f"{k} = %s")
            vals.append(v if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False))
        
        vals.append(op_id)
        query = f"UPDATE ai_operations SET {', '.join(cols)} WHERE id = ?" if self._db.dialect == "sqlite" else f"UPDATE ai_operations SET {', '.join(cols)} WHERE id = %s"
        self._db.execute(query, tuple(vals))

from __future__ import annotations

import json
from typing import Any

from app.database import Database
from app.models import new_id, utc_now


class AuditService:
    def __init__(self, db: Database) -> None:
        self._db = db

    def log(
        self,
        *,
        actor_id: str | None,
        action: str,
        target_type: str,
        target_id: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._db.execute(
            """
            INSERT INTO audit_logs (id, actor_id, action, target_type, target_id, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("aud"),
                actor_id,
                action,
                target_type,
                target_id,
                json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                utc_now(),
            ),
        )

    def list_logs(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        actor_id: str | None = None,
        action_prefix: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if target_type:
            conditions.append("target_type = ?")
            params.append(target_type)
        if target_id:
            conditions.append("target_id = ?")
            params.append(target_id)
        if actor_id:
            conditions.append("actor_id = ?")
            params.append(actor_id)
        if action_prefix:
            conditions.append("action LIKE ?")
            params.append(f"{action_prefix}%")
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._db.fetchall(
            f"""
            SELECT id, actor_id, action, target_type, target_id, payload_json, created_at
            FROM audit_logs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            tuple([*params, max(1, min(limit, 500))]),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            payload: dict[str, Any] | None = None
            raw = row.get("payload_json")
            if isinstance(raw, str) and raw.strip():
                try:
                    decoded = json.loads(raw)
                    if isinstance(decoded, dict):
                        payload = decoded
                except json.JSONDecodeError:
                    payload = None
            result.append(
                {
                    "id": row["id"],
                    "actorId": row.get("actor_id"),
                    "action": row["action"],
                    "targetType": row["target_type"],
                    "targetId": row["target_id"],
                    "payload": payload,
                    "createdAt": row["created_at"],
                }
            )
        return result

    def list_team_logs(
        self,
        *,
        team_id: str,
        actor_id: str | None = None,
        action_prefix: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        # 1) direct team-level operations
        direct = self.list_logs(
            target_type="team",
            target_id=team_id,
            actor_id=actor_id,
            action_prefix=action_prefix,
            limit=limit,
        )
        # 2) team member operations (team_id kept in payload.teamId)
        member_action_prefix = action_prefix if action_prefix else "team.member."
        member_ops = self.list_logs(
            target_type="team_member",
            actor_id=actor_id,
            action_prefix=member_action_prefix,
            limit=max(limit * 3, 200),
        )
        related_member_ops = [
            row
            for row in member_ops
            if isinstance(row.get("payload"), dict) and str(row["payload"].get("teamId") or "") == team_id
        ]
        combined = sorted([*direct, *related_member_ops], key=lambda item: str(item.get("createdAt") or ""), reverse=True)
        return combined[: max(1, min(limit, 500))]

    def delete_log(self, log_id: str) -> bool:
        affected = self._db.execute(
            """
            DELETE FROM audit_logs
            WHERE id = ?
            """,
            (log_id,),
        )
        return affected > 0

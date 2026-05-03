from typing import Any, List, Optional
from app.database import Database
from app.core.utils import new_id, utc_now

class TeamRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get_user_org_ids(self, user_id: str) -> List[str]:
        query = """
            SELECT DISTINCT t.org_id 
            FROM teams t 
            JOIN team_members tm ON t.id = tm.team_id 
            WHERE tm.user_id = ?
        """ if self._db.dialect == "sqlite" else """
            SELECT DISTINCT t.org_id 
            FROM teams t 
            JOIN team_members tm ON t.id = tm.team_id 
            WHERE tm.user_id = %s
        """
        rows = self._db.fetchall(query, (user_id,))
        return [r["org_id"] for r in rows]

    def list_org_members(self, org_ids: List[str]) -> List[dict[str, Any]]:
        if not org_ids:
            return []
        placeholders = ",".join(["?"]*(len(org_ids))) if self._db.dialect == "sqlite" else ",".join(["%s"]*(len(org_ids)))
        query = f"""
            SELECT DISTINCT u.id as user_id, u.username, u.name, tm.role, tm.created_at, tm.id
            FROM users u
            JOIN team_members tm ON u.id = tm.user_id
            JOIN teams t ON tm.team_id = t.id
            WHERE t.org_id IN ({placeholders})
            ORDER BY u.name ASC
        """
        return [dict(r) for r in self._db.fetchall(query, tuple(org_ids))]

    def get_teams_by_user(self, user_id: str) -> List[dict[str, Any]]:
        query = """
            SELECT t.*, (SELECT COUNT(*) FROM team_members tm2 WHERE tm2.team_id = t.id) as member_count
            FROM teams t
            JOIN team_members tm ON t.id = tm.team_id
            WHERE tm.user_id = ?
            ORDER BY t.created_at DESC
        """ if self._db.dialect == "sqlite" else """
            SELECT t.*, (SELECT COUNT(*) FROM team_members tm2 WHERE tm2.team_id = t.id) as member_count
            FROM teams t
            JOIN team_members tm ON t.id = tm.team_id
            WHERE tm.user_id = %s
            ORDER BY t.created_at DESC
        """
        return [dict(r) for r in self._db.fetchall(query, (user_id,))]

    def list_team_members(self, team_id: str) -> List[dict[str, Any]]:
        query = """
            SELECT tm.*, u.username, u.name
            FROM team_members tm
            JOIN users u ON tm.user_id = u.id
            WHERE tm.team_id = ?
            ORDER BY tm.created_at ASC
        """ if self._db.dialect == "sqlite" else """
            SELECT tm.*, u.username, u.name
            FROM team_members tm
            JOIN users u ON tm.user_id = u.id
            WHERE tm.team_id = %s
            ORDER BY tm.created_at ASC
        """
        return [dict(r) for r in self._db.fetchall(query, (team_id,))]

    def get_team_by_id(self, team_id: str) -> Optional[dict[str, Any]]:
        query = "SELECT * FROM teams WHERE id = ?" if self._db.dialect == "sqlite" else "SELECT * FROM teams WHERE id = %s"
        row = self._db.fetchone(query, (team_id,))
        return dict(row) if row else None

    def create_team(self, *, team_id: str, org_id: str, name: str, now: str) -> dict[str, Any]:
        query = (
            "INSERT INTO teams (id, org_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)"
            if self._db.dialect == "sqlite"
            else "INSERT INTO teams (id, org_id, name, created_at, updated_at) VALUES (%s, %s, %s, %s, %s)"
        )
        self._db.execute(query, (team_id, org_id, name, now, now))
        created = self.get_team_by_id(team_id)
        return created or {"id": team_id, "org_id": org_id, "name": name, "created_at": now, "updated_at": now}

    def add_team_member(self, *, member_id: str, team_id: str, user_id: str, role: str, now: str) -> dict[str, Any]:
        query = (
            "INSERT INTO team_members (id, team_id, user_id, role, created_at) VALUES (?, ?, ?, ?, ?)"
            if self._db.dialect == "sqlite"
            else "INSERT INTO team_members (id, team_id, user_id, role, created_at) VALUES (%s, %s, %s, %s, %s)"
        )
        self._db.execute(query, (member_id, team_id, user_id, role, now))
        row = self._db.fetchone(
            """
            SELECT tm.*, u.username, u.name
            FROM team_members tm
            JOIN users u ON tm.user_id = u.id
            WHERE tm.id = ?
            """
            if self._db.dialect == "sqlite"
            else """
            SELECT tm.*, u.username, u.name
            FROM team_members tm
            JOIN users u ON tm.user_id = u.id
            WHERE tm.id = %s
            """,
            (member_id,),
        )
        return dict(row) if row else {"id": member_id, "team_id": team_id, "user_id": user_id, "role": role, "created_at": now}

    def find_team_member_by_user(self, team_id: str, user_id: str) -> Optional[dict[str, Any]]:
        query = (
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?"
            if self._db.dialect == "sqlite"
            else "SELECT * FROM team_members WHERE team_id = %s AND user_id = %s"
        )
        row = self._db.fetchone(query, (team_id, user_id))
        return dict(row) if row else None

    def find_team_member_by_id(self, member_id: str) -> Optional[dict[str, Any]]:
        query = "SELECT * FROM team_members WHERE id = ?" if self._db.dialect == "sqlite" else "SELECT * FROM team_members WHERE id = %s"
        row = self._db.fetchone(query, (member_id,))
        return dict(row) if row else None

    def update_team_member_role(self, member_id: str, role: str) -> int:
        query = "UPDATE team_members SET role = ? WHERE id = ?" if self._db.dialect == "sqlite" else "UPDATE team_members SET role = %s WHERE id = %s"
        return self._db.execute(query, (role, member_id))

    def remove_team_member(self, member_id: str) -> int:
        query = "DELETE FROM team_members WHERE id = ?" if self._db.dialect == "sqlite" else "DELETE FROM team_members WHERE id = %s"
        return self._db.execute(query, (member_id,))

    def count_team_members_by_role(self, team_id: str, role: str) -> int:
        query = (
            "SELECT COUNT(*) AS total FROM team_members WHERE team_id = ? AND role = ?"
            if self._db.dialect == "sqlite"
            else "SELECT COUNT(*) AS total FROM team_members WHERE team_id = %s AND role = %s"
        )
        row = self._db.fetchone(query, (team_id, role))
        return int(row["total"]) if row and row.get("total") is not None else 0

from __future__ import annotations

from typing import Any, List, Optional
from app.core.utils import new_id, utc_now
from app.repositories.team_repo import TeamRepository

class TeamService:
    def __init__(self, repo: TeamRepository) -> None:
        self._repo = repo

    def list_organization_members(self, org_ids: List[str]) -> List[dict[str, Any]]:
        return self._repo.list_org_members(org_ids)

    def get_user_teams(self, user_id: str) -> List[dict[str, Any]]:
        return self._repo.get_teams_by_user(user_id)

    def list_team_members(self, team_id: str) -> List[dict[str, Any]]:
        return self._repo.list_team_members(team_id)

    def get_user_org_ids(self, user_id: str) -> List[str]:
        return self._repo.get_user_org_ids(user_id)

    def create_team(self, *, org_id: str, name: str, creator_user_id: str) -> dict[str, Any]:
        team_name = name.strip()
        if not team_name:
            raise ValueError("团队名称不能为空")
        team = self._repo.create_team(
            team_id=new_id("team"),
            org_id=org_id.strip() or "DEFAULT_ORG",
            name=team_name,
            now=utc_now(),
        )
        # creator joins as owner by default
        existing = self._repo.find_team_member_by_user(team["id"], creator_user_id)
        if not existing:
            self._repo.add_team_member(
                member_id=new_id("tm"),
                team_id=team["id"],
                user_id=creator_user_id,
                role="owner",
                now=utc_now(),
            )
        return team

    def _get_operator_role(self, team_id: str, operator_user_id: str) -> str:
        operator = self._repo.find_team_member_by_user(team_id, operator_user_id)
        if not operator:
            raise PermissionError("当前用户不在该团队中")
        return str(operator.get("role") or "member").lower()

    def _ensure_manage_permission(self, team_id: str, operator_user_id: str) -> str:
        operator_role = self._get_operator_role(team_id, operator_user_id)
        if operator_role not in {"owner", "admin"}:
            raise PermissionError("仅 owner/admin 可管理团队成员")
        return operator_role

    def add_member(self, *, team_id: str, user_id: str, role: str, operator_user_id: str) -> dict[str, Any]:
        normalized_role = (role or "member").strip().lower()
        if normalized_role not in {"owner", "admin", "member"}:
            raise ValueError("无效成员角色")
        team = self._repo.get_team_by_id(team_id)
        if not team:
            raise KeyError("team not found")
        operator_role = self._ensure_manage_permission(team_id, operator_user_id)
        if normalized_role == "owner" and operator_role != "owner":
            raise PermissionError("仅 owner 可新增 owner")
        exists = self._repo.find_team_member_by_user(team_id, user_id)
        if exists:
            raise ValueError("成员已存在")
        return self._repo.add_team_member(
            member_id=new_id("tm"),
            team_id=team_id,
            user_id=user_id,
            role=normalized_role,
            now=utc_now(),
        )

    def update_member_role(self, *, team_id: str, member_id: str, role: str, operator_user_id: str) -> dict[str, Any]:
        normalized_role = (role or "").strip().lower()
        if normalized_role not in {"owner", "admin", "member"}:
            raise ValueError("无效成员角色")
        operator_role = self._ensure_manage_permission(team_id, operator_user_id)
        member = self._repo.find_team_member_by_id(member_id)
        if not member or member.get("team_id") != team_id:
            raise KeyError("member not found")
        current_role = str(member.get("role") or "member").lower()
        if normalized_role == "owner" and operator_role != "owner":
            raise PermissionError("仅 owner 可设置 owner")
        if current_role == "owner" and normalized_role != "owner":
            owner_count = self._repo.count_team_members_by_role(team_id, "owner")
            if owner_count <= 1:
                raise ValueError("团队至少需要保留一名 owner")
        self._repo.update_team_member_role(member_id, normalized_role)
        updated = self._repo.find_team_member_by_id(member_id)
        if not updated:
            raise KeyError("member not found")
        return updated

    def remove_member(self, *, team_id: str, member_id: str, operator_user_id: str) -> bool:
        self._ensure_manage_permission(team_id, operator_user_id)
        member = self._repo.find_team_member_by_id(member_id)
        if not member or member.get("team_id") != team_id:
            return False
        current_role = str(member.get("role") or "member").lower()
        if current_role == "owner":
            owner_count = self._repo.count_team_members_by_role(team_id, "owner")
            if owner_count <= 1:
                raise ValueError("团队至少需要保留一名 owner")
        return self._repo.remove_team_member(member_id) > 0

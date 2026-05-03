from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status, Response, Query
from app.models import (
    TeamInfo, TeamCreateRequest, TeamMemberPublic, 
    TeamMemberAddRequest, TeamUpdateRequest,
    utc_now, new_id
)
from app.routers.deps import get_current_user, get_user_auth, get_teams, get_user_org_ids, get_audit

router = APIRouter(prefix="/teams", tags=["teams"])

@router.get("", response_model=List[TeamMemberPublic])
async def list_organization_members(
    org_ids: list[str] = Depends(get_user_org_ids),
    team_service = Depends(get_teams)
) -> List[dict]:
    # For the "Team Management" tab in Settings, we usually want to see people 
    # in the same organization, as identified by their team memberships.
    members = team_service.list_organization_members(org_ids)
    
    return [{
        "id": r["id"],
        "userId": r["user_id"],
        "username": r["username"],
        "name": r["name"],
        "role": r["role"],
        "createdAt": r["created_at"]
    } for r in members]

@router.post("", response_model=TeamInfo)
async def create_team(
    payload: TeamCreateRequest,
    current_user: dict = Depends(get_current_user),
    team_service = Depends(get_teams),
    audit = Depends(get_audit),
) -> dict:
    try:
        created = team_service.create_team(
            org_id=payload.orgId,
            name=payload.name,
            creator_user_id=current_user["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = {
        "id": created["id"],
        "orgId": created["org_id"],
        "name": created["name"],
        "createdAt": created["created_at"],
        "memberCount": 1,
    }
    audit.log(
        actor_id=current_user["id"],
        action="team.create",
        target_type="team",
        target_id=created["id"],
        payload={"orgId": created["org_id"], "name": created["name"]},
    )
    return result

@router.get("/list", response_model=List[TeamInfo])
async def get_teams_list(
    current_user: dict = Depends(get_current_user), 
    team_service = Depends(get_teams)
) -> List[dict]:
    teams = team_service.get_user_teams(current_user["id"])
    return [{
        "id": row["id"],
        "orgId": row["org_id"],
        "name": row["name"],
        "createdAt": row["created_at"],
        "memberCount": row["member_count"]
    } for row in teams]

@router.get("/{team_id}/members", response_model=List[TeamMemberPublic])
async def list_specific_team_members(
    team_id: str,
    current_user: dict = Depends(get_current_user),
    team_service = Depends(get_teams)
) -> List[dict]:
    members = team_service.list_team_members(team_id)
    return [{
        "id": r["id"],
        "userId": r["user_id"],
        "username": r["username"],
        "name": r["name"],
        "role": r["role"],
        "createdAt": r["created_at"]
    } for r in members]

@router.post("/{team_id}/members", response_model=TeamMemberPublic)
async def add_team_member(
    team_id: str,
    payload: TeamMemberAddRequest,
    current_user: dict = Depends(get_current_user),
    team_service = Depends(get_teams),
    audit = Depends(get_audit),
) -> dict:
    try:
        member = team_service.add_member(
            team_id=team_id,
            user_id=payload.userId,
            role=payload.role,
            operator_user_id=current_user["id"],
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="团队不存在")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = {
        "id": member["id"],
        "userId": member["user_id"],
        "username": member.get("username", ""),
        "name": member.get("name", ""),
        "teamId": member["team_id"],
        "role": member["role"],
        "createdAt": member["created_at"],
    }
    audit.log(
        actor_id=current_user["id"],
        action="team.member.add",
        target_type="team_member",
        target_id=member["id"],
        payload={"teamId": team_id, "userId": member["user_id"], "role": member["role"]},
    )
    return result

@router.patch("/{team_id}/members/{member_id}", response_model=TeamMemberPublic)
async def update_team_member_role(
    team_id: str,
    member_id: str,
    payload: dict[str, Any],
    current_user: dict = Depends(get_current_user),
    team_service = Depends(get_teams),
    audit = Depends(get_audit),
) -> dict:
    role = str(payload.get("role") or "").strip().lower()
    try:
        updated = team_service.update_member_role(
            team_id=team_id,
            member_id=member_id,
            role=role,
            operator_user_id=current_user["id"],
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="成员不存在")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Enrich with username/name from team member list for consistent response.
    rows = team_service.list_team_members(team_id)
    row = next((item for item in rows if item["id"] == member_id), None)
    if row:
        result = {
            "id": row["id"],
            "userId": row["user_id"],
            "username": row.get("username", ""),
            "name": row.get("name", ""),
            "teamId": row["team_id"],
            "role": row["role"],
            "createdAt": row["created_at"],
        }
        audit.log(
            actor_id=current_user["id"],
            action="team.member.role.update",
            target_type="team_member",
            target_id=row["id"],
            payload={"teamId": team_id, "userId": row["user_id"], "role": row["role"]},
        )
        return result
    result = {
        "id": updated["id"],
        "userId": updated["user_id"],
        "username": "",
        "name": "",
        "teamId": updated["team_id"],
        "role": updated["role"],
        "createdAt": updated["created_at"],
    }
    audit.log(
        actor_id=current_user["id"],
        action="team.member.role.update",
        target_type="team_member",
        target_id=updated["id"],
        payload={"teamId": team_id, "userId": updated["user_id"], "role": updated["role"]},
    )
    return result

@router.delete("/{team_id}/members/{member_id}", status_code=204)
async def remove_team_member(
    team_id: str,
    member_id: str,
    current_user: dict = Depends(get_current_user),
    team_service = Depends(get_teams),
    audit = Depends(get_audit),
) -> Response:
    members = team_service.list_team_members(team_id)
    target = next((m for m in members if m.get("id") == member_id), None)
    try:
        ok = team_service.remove_member(team_id=team_id, member_id=member_id, operator_user_id=current_user["id"])
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=404, detail="成员不存在")
    audit.log(
        actor_id=current_user["id"],
        action="team.member.remove",
        target_type="team_member",
        target_id=member_id,
        payload={
            "teamId": team_id,
            "userId": target.get("user_id") if isinstance(target, dict) else None,
            "role": target.get("role") if isinstance(target, dict) else None,
        },
    )
    return Response(status_code=204)

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.routers.deps import get_current_user, get_audit

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs")
async def list_audit_logs(
    teamId: str | None = Query(default=None),
    targetType: str | None = Query(default=None),
    targetId: str | None = Query(default=None),
    actorId: str | None = Query(default=None),
    actionPrefix: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=500),
    _: dict = Depends(get_current_user),
    audit = Depends(get_audit),
) -> dict:
    if teamId:
        items = audit.list_team_logs(
            team_id=teamId,
            actor_id=actorId,
            action_prefix=actionPrefix,
            limit=limit,
        )
        return {"items": items}
    items = audit.list_logs(
        target_type=targetType,
        target_id=targetId,
        actor_id=actorId,
        action_prefix=actionPrefix,
        limit=limit,
    )
    return {"items": items}

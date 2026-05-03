from fastapi import APIRouter, Depends, Query, HTTPException, status
from typing import Any
from pydantic import BaseModel

from .deps import get_current_user, get_db, get_user_org_ids
from ..database import Database

router = APIRouter(prefix="/specs", tags=["source_specs"])


class SourceSpecPublic(BaseModel):
    id: str
    projectId: str
    title: str
    kind: str = "requirement"
    content: str = ""
    createdBy: str | None = None
    createdAt: str
    updatedAt: str


def _row_to_spec(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "projectId": row["project_id"],
        "title": row["title"],
        "kind": "requirement",
        "content": row.get("content", ""),
        "createdBy": row.get("created_by"),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


@router.get("")
async def list_specs(
    projectId: str | None = Query(None),
    _: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    if projectId:
        rows = db.fetchall(
            "SELECT * FROM requirements WHERE project_id = %s AND deleted_at IS NULL ORDER BY created_at DESC" if db.dialect != "sqlite" else "SELECT * FROM requirements WHERE project_id = ? AND deleted_at IS NULL ORDER BY created_at DESC",
            (projectId,)
        )
    else:
        rows = db.fetchall(
            "SELECT * FROM requirements WHERE deleted_at IS NULL ORDER BY created_at DESC"
        )
    return [_row_to_spec(row) for row in rows]


@router.get("/{spec_id}")
async def get_spec(
    spec_id: str,
    _: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    row = db.fetchone(
        "SELECT * FROM requirements WHERE id = %s AND deleted_at IS NULL" if db.dialect != "sqlite" else "SELECT * FROM requirements WHERE id = ? AND deleted_at IS NULL",
        (spec_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="需求文档不存在")
    return _row_to_spec(row)

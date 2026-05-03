from fastapi import APIRouter, Depends, Query, HTTPException, status, Response
from typing import List, Optional
from .deps import get_current_user, get_db, get_projects, get_user_org_ids, require_roles
from ..models import Project, ProjectListResponse, CreateProjectRequest, UpdateProjectRequest

router = APIRouter(prefix="/projects", tags=["projects"])

@router.get("", response_model=List[Project])
async def list_projects(
    org_ids: list[str] = Depends(get_user_org_ids),
    project_service = Depends(get_projects)
) -> List[Project]:
    projects = project_service.list_projects(org_ids)
    return [Project.model_validate(p) for p in projects]

@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: CreateProjectRequest,
    current_user: dict = Depends(require_roles("admin", "tester")),
    org_ids: list[str] = Depends(get_user_org_ids),
    project_service = Depends(get_projects)
) -> Project:
    if not payload.name or not payload.name.strip():
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    org_id = org_ids[0] if org_ids else "DEFAULT_ORG"
    created = project_service.create_project(
        org_id=org_id,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else ""
    )
    return Project.model_validate(created)

@router.get("/search", response_model=ProjectListResponse)
async def search_projects(
    q: str | None = Query(None, max_length=256),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortBy: str = Query("created_at"),
    sortOrder: str = Query("desc"),
    org_ids: list[str] = Depends(get_user_org_ids),
    project_service = Depends(get_projects)
) -> ProjectListResponse:
    result = project_service.search_projects(
        org_ids=org_ids,
        query_text=q,
        page=page,
        page_size=pageSize,
        sort_by=sortBy,
        sort_order=sortOrder
    )
    
    items = [Project.model_validate(row) for row in result["items"]]
    
    return ProjectListResponse(
        items=items,
        total=result["total"],
        page=page,
        pageSize=pageSize,
        hasNext=( (page - 1) * pageSize + len(items) ) < result["total"]
    )

@router.get("/recycle-bin", response_model=ProjectListResponse)
async def list_recycle_bin(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    org_ids: list[str] = Depends(get_user_org_ids),
    project_service = Depends(get_projects)
) -> ProjectListResponse:
    result = project_service.list_deleted_projects(
        org_ids=org_ids,
        page=page,
        page_size=pageSize
    )
    items = [Project.model_validate(row) for row in result["items"]]
    return ProjectListResponse(
        items=items,
        total=result["total"],
        page=page,
        pageSize=pageSize,
        hasNext=(page * pageSize) < result["total"]
    )

@router.get("/{project_id}", response_model=Project)
async def get_project(
    project_id: str,
    _: dict = Depends(get_current_user),
    project_service = Depends(get_projects)
) -> Project:
    project = project_service.get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return Project.model_validate(project)

@router.patch("/{project_id}", response_model=Project)
async def update_project(
    project_id: str,
    payload: UpdateProjectRequest,
    current_user: dict = Depends(require_roles("admin", "tester")),
    project_service = Depends(get_projects)
) -> Project:
    updated = project_service.update_project(
        project_id,
        name=payload.name,
        description=payload.description
    )
    if not updated or not updated.get("id"):
        raise HTTPException(status_code=404, detail="项目不存在")
    return Project.model_validate(updated)

@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    current_user: dict = Depends(require_roles("admin", "tester")),
    project_service = Depends(get_projects)
):
    project = project_service.get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project_service.delete_project(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post("/{project_id}/restore", response_model=Project)
async def restore_project(
    project_id: str,
    current_user: dict = Depends(require_roles("admin", "tester")),
    project_service = Depends(get_projects)
) -> Project:
    restored = project_service.restore_project(project_id)
    if not restored:
        raise HTTPException(status_code=404, detail="项目不存在或未被删除")
    return Project.model_validate(restored)


@router.delete("/{project_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
async def purge_project(
    project_id: str,
    current_user: dict = Depends(require_roles("admin", "tester")),
    project_service = Depends(get_projects),
):
    ok = project_service.purge_deleted_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="项目不存在或不在回收站")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/recycle-bin/batch-delete")
async def batch_purge_projects(
    payload: dict,
    current_user: dict = Depends(require_roles("admin", "tester")),
    project_service = Depends(get_projects),
):
    ids = payload.get("ids") if isinstance(payload, dict) else None
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids is required")
    deleted = 0
    failed_ids: list[str] = []
    for raw in ids:
        project_id = str(raw or "").strip()
        if not project_id:
            continue
        if project_service.purge_deleted_project(project_id):
            deleted += 1
        else:
            failed_ids.append(project_id)
    return {"deleted": deleted, "failedIds": failed_ids}

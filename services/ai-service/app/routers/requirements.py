from fastapi import APIRouter, Depends, HTTPException, Query, status, Response, UploadFile, File, Form
from fastapi.responses import JSONResponse
from typing import Any, List, Optional
from .deps import get_current_user, require_roles, get_requirement_analysis, get_analysis_queue, get_lock_service, get_store, get_user_org_ids
from ..models import (
    RequirementPublic,
    RequirementCreateRequest,
    RequirementUpdateRequest,
    RequirementBatchDeleteRequest,
    RequirementImportResult,
    RequirementImportPreviewResult,
    RequirementAnalysisPublic,
    RequirementAnalyzeResult,
    utc_now,
)

router = APIRouter(prefix="/requirements", tags=["requirements"])

@router.get("", response_model=dict[str, Any])
async def list_requirements(
    projectId: str | None = Query(None),
    q: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortBy: str = Query("createdAt"),
    sortOrder: str = Query("desc"),
    org_ids: list[str] = Depends(get_user_org_ids),
    service = Depends(get_requirement_analysis),
) -> dict[str, Any]:
    return service.list_requirements(
        org_ids=org_ids,
        project_id=projectId,
        q=q,
        status=status,
        page=page,
        page_size=pageSize,
        sort_by=sortBy,
        sort_order=sortOrder,
    )

@router.get("/search", response_model=dict[str, Any])
async def search_requirements(
    projectId: str | None = Query(None),
    q: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortBy: str = Query("createdAt"),
    sortOrder: str = Query("desc"),
    org_ids: list[str] = Depends(get_user_org_ids),
    service = Depends(get_requirement_analysis),
) -> dict[str, Any]:
    return service.list_requirements(
        org_ids=org_ids,
        project_id=projectId,
        q=q,
        status=status,
        page=page,
        page_size=pageSize,
        sort_by=sortBy,
        sort_order=sortOrder,
    )

@router.get("/recycle-bin", response_model=dict[str, Any])
async def list_recycle_bin(
    projectId: str | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    org_ids: list[str] = Depends(get_user_org_ids),
    service = Depends(get_requirement_analysis),
) -> dict[str, Any]:
    return service.list_deleted_requirements(
        org_ids=org_ids,
        project_id=projectId,
        page=page,
        page_size=pageSize,
    )

@router.post("", response_model=RequirementPublic, status_code=status.HTTP_201_CREATED)
async def create_requirement(
    payload: RequirementCreateRequest,
    current_user: dict = Depends(require_roles("admin", "tester")),
    org_ids: list[str] = Depends(get_user_org_ids),
    service = Depends(get_requirement_analysis),
) -> RequirementPublic:
    try:
        org_id = org_ids[0] if org_ids else "DEFAULT_ORG"
        created = service.create_requirement(
            org_id=org_id,
            project_id=payload.projectId,
            title=payload.title,
            content=payload.content,
            source_spec_id=payload.sourceSpecId,
            tags=payload.tags,
            created_by=current_user["id"],
        )
        return RequirementPublic.model_validate(created)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/batch-delete")
async def batch_delete_requirements(
    payload: RequirementBatchDeleteRequest,
    hard: bool = Query(False),
    current_user: dict = Depends(require_roles("admin", "tester")),
    service = Depends(get_requirement_analysis),
):
    count = service.batch_delete_requirements(payload.requirementIds, hard=hard)
    return {"deleted": count}


@router.post("/batch-restore")
async def batch_restore_requirements(
    payload: RequirementBatchDeleteRequest,
    current_user: dict = Depends(require_roles("admin", "tester")),
    service = Depends(get_requirement_analysis),
):
    count = service.batch_restore_requirements(payload.requirementIds)
    return {"restored": count}


@router.post("/import/preview", response_model=RequirementImportPreviewResult)
async def preview_import_requirements(
    projectId: str = Form(...),
    dedupe: bool = Form(True),
    strictTemplate: bool = Form(False),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_roles("admin", "tester")),
    org_ids: list[str] = Depends(get_user_org_ids),
    service = Depends(get_requirement_analysis),
) -> RequirementImportPreviewResult:
    org_id = org_ids[0] if org_ids else "DEFAULT_ORG"
    file_bytes = await file.read()
    records, parse_warnings = service._parse_import_records(
        file_name=file.filename or "import.txt",
        file_bytes=file_bytes,
    )
    
    total = len(records)
    valid = 0
    duplicates = 0
    invalid = 0
    
    for record in records:
        title = record.get("title", "")
        content = record.get("content", "")
        if not title and not content:
            invalid += 1
            continue
        if dedupe and service._exists_same_requirement(projectId, title, content):
            duplicates += 1
            continue
        valid += 1
    
    return RequirementImportPreviewResult(
        total=total,
        valid=valid,
        duplicates=duplicates,
        invalid=invalid,
    )


@router.post("/import", response_model=RequirementImportResult)
async def import_requirements(
    projectId: str = Form(...),
    dedupe: bool = Form(True),
    rollbackOnError: bool = Form(False),
    strictTemplate: bool = Form(False),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_roles("admin", "tester")),
    org_ids: list[str] = Depends(get_user_org_ids),
    service = Depends(get_requirement_analysis),
) -> RequirementImportResult:
    org_id = org_ids[0] if org_ids else "DEFAULT_ORG"
    file_bytes = await file.read()
    result = service.import_requirements(
        org_id=org_id,
        project_id=projectId,
        file_name=file.filename or "import.txt",
        file_bytes=file_bytes,
        created_by=current_user["id"],
        dedupe=dedupe,
        rollback_on_error=rollbackOnError,
    )
    return RequirementImportResult(
        total=result["total"],
        created=[RequirementPublic.model_validate(item) for item in result["created"]],
        warnings=result["warnings"],
    )


@router.get("/{requirement_id}", response_model=RequirementPublic)
async def get_requirement(
    requirement_id: str,
    _: dict = Depends(get_current_user),
    service = Depends(get_requirement_analysis),
) -> RequirementPublic:
    requirement = service.get_requirement(requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="requirement not found")
    return RequirementPublic.model_validate(requirement)

@router.patch("/{requirement_id}", response_model=RequirementPublic)
async def update_requirement(
    requirement_id: str,
    payload: RequirementUpdateRequest,
    current_user: dict = Depends(require_roles("admin", "tester")),
    service = Depends(get_requirement_analysis),
) -> RequirementPublic:
    try:
        updated = service.update_requirement(
            requirement_id=requirement_id,
            updates=payload.model_dump(exclude_unset=True),
        )
        return RequirementPublic.model_validate(updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.delete("/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_requirement(
    requirement_id: str,
    hard: bool = Query(False),
    current_user: dict = Depends(require_roles("admin", "tester")),
    service = Depends(get_requirement_analysis),
):
    success = service.delete_requirement(requirement_id, hard=hard)
    if not success:
        raise HTTPException(status_code=404, detail="requirement not found or already deleted")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post("/{requirement_id}/restore", response_model=RequirementPublic)
async def restore_requirement(
    requirement_id: str,
    current_user: dict = Depends(require_roles("admin", "tester")),
    service = Depends(get_requirement_analysis),
) -> RequirementPublic:
    restored = service.restore_requirement(requirement_id)
    if not restored:
        raise HTTPException(status_code=404, detail="requirement not found or not deleted")
    return RequirementPublic.model_validate(restored)

@router.get("/{requirement_id}/analysis/latest", response_model=RequirementAnalysisPublic)
async def get_latest_analysis(
    requirement_id: str,
    _: dict = Depends(get_current_user),
    service = Depends(get_requirement_analysis),
) -> RequirementAnalysisPublic:
    analysis = service.get_latest_analysis(requirement_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="no analysis found for this requirement")
    return RequirementAnalysisPublic.model_validate(analysis)

@router.post("/{requirement_id}/analyze", response_model=dict[str, Any])
async def start_analysis(
    requirement_id: str,
    current_user: dict = Depends(require_roles("admin", "tester")),
    service = Depends(get_requirement_analysis),
) -> dict[str, Any]:
    try:
        operation = service.create_analysis_operation(
            requirement_id=requirement_id,
            created_by=current_user["id"],
        )
        return operation
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

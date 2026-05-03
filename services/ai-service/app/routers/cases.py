from fastapi import APIRouter, Depends, Query, HTTPException, status, Response, Request
from typing import List, Optional, Any
import logging
from .deps import get_current_user, require_roles, get_test_cases, get_audit, get_lock_service, get_test_runs
from ..models import (
    TestCase, 
    TestCaseListResponse, 
    TestCaseCreateRequest, 
    TestCaseUpdateRequest,
    TestRun
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cases", tags=["cases"])

@router.get("/runs", response_model=List[TestRun])
async def list_runs(
    projectId: str | None = Query(None),
    _: dict = Depends(get_current_user),
    test_runs: Any = Depends(get_test_runs),
) -> List[TestRun]:
    if not projectId:
        return []
    rows = test_runs.list_runs(project_id=projectId)
    return [TestRun.model_validate(item) for item in rows]

@router.get("", response_model=TestCaseListResponse)
async def list_cases(
    projectId: str | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortBy: str = Query("createdAt"),
    sortOrder: str = Query("desc"),
    _: dict = Depends(get_current_user),
    test_cases: Any = Depends(get_test_cases),
) -> TestCaseListResponse:
    col_map = {"createdAt": "created_at", "updatedAt": "updated_at", "title": "title"}
    db_sort_by = col_map.get(sortBy, "created_at")
    
    result = test_cases.list_cases(
        project_id=projectId,
        q=q,
        page=page,
        page_size=pageSize,
        sort_by=db_sort_by,
        sort_order=sortOrder,
    )
    
    def prepare_item(item: dict):
        import json
        for col in ("steps_json", "assertion_hints_json", "payload_json"):
            if col in item and isinstance(item[col], str):
                item[col] = json.loads(item[col])
        return item

    return TestCaseListResponse(
        items=[TestCase.model_validate(prepare_item(dict(item))) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        pageSize=result["pageSize"],
        hasNext=result["hasNext"],
    )

@router.get("/search", response_model=TestCaseListResponse)
async def search_cases(
    projectId: str | None = Query(None),
    q: str | None = Query(None),
    kind: str | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortBy: str = Query("updatedAt"),
    sortOrder: str = Query("desc"),
    _: dict = Depends(get_current_user),
    test_cases: Any = Depends(get_test_cases),
) -> TestCaseListResponse:
    col_map = {"createdAt": "created_at", "updatedAt": "updated_at", "title": "title"}
    db_sort_by = col_map.get(sortBy, "updated_at")
    
    result = test_cases.list_cases(
        project_id=projectId,
        kind=kind,
        q=q,
        page=page,
        page_size=pageSize,
        sort_by=db_sort_by,
        sort_order=sortOrder,
    )
    
    def prepare_item(item: dict):
        import json
        for col in ("steps_json", "assertion_hints_json", "payload_json"):
            if col in item and isinstance(item[col], str):
                item[col] = json.loads(item[col])
        return item

    return TestCaseListResponse(
        items=[TestCase.model_validate(prepare_item(dict(item))) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        pageSize=result["pageSize"],
        hasNext=result["hasNext"],
    )

@router.post("", response_model=TestCase, status_code=status.HTTP_201_CREATED)
async def create_case(
    payload: TestCaseCreateRequest,
    current_user: dict = Depends(require_roles("admin", "tester")),
    test_cases: Any = Depends(get_test_cases),
) -> TestCase:
    import json
    data = {
        "projectId": payload.projectId,
        "specId": payload.specId,
        "kind": payload.kind,
        "title": payload.title,
        "objective": payload.objective,
        "stepsJson": json.dumps(payload.steps),
        "assertionHintsJson": json.dumps(payload.assertionHints),
        "payloadJson": json.dumps(payload.payload),
        "createdBy": current_user["id"],
    }
    created = test_cases._repo.create(data)
    
    for col in ("steps_json", "assertion_hints_json", "payload_json"):
        if col in created and isinstance(created[col], str):
            created[col] = json.loads(created[col])
            
    return TestCase.model_validate(dict(created))

@router.post("/batch-delete", status_code=status.HTTP_200_OK)
async def batch_delete_cases(
    request: Request,
    _: dict = Depends(require_roles("admin", "tester")),
    test_cases: Any = Depends(get_test_cases),
) -> dict:
    import json
    body = json.loads(await request.body())
    case_ids = body.get("caseIds", [])
    if not case_ids:
        return {"deleted": 0}
    
    deleted_count = test_cases.batch_delete(case_ids)
    return {"deleted": deleted_count}

@router.get("/{case_id}", response_model=TestCase)
async def get_case(
    case_id: str,
    _: dict = Depends(get_current_user),
    test_cases: Any = Depends(get_test_cases),
) -> TestCase:
    import json
    case = test_cases.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="测试用例不存在")
    
    for col in ("steps_json", "assertion_hints_json", "payload_json"):
        if col in case and isinstance(case[col], str):
            case[col] = json.loads(case[col])
    
    return TestCase.model_validate(dict(case))

@router.patch("/{case_id}", response_model=TestCase)
async def update_case(
    case_id: str,
    payload: TestCaseUpdateRequest,
    _: dict = Depends(require_roles("admin", "tester")),
    test_cases: Any = Depends(get_test_cases),
) -> TestCase:
    import json
    existing = test_cases.get_case(case_id)
    if not existing:
        raise HTTPException(status_code=404, detail="测试用例不存在")
    
    logger.info(f"Updating case {case_id} with payload: {payload.payload}")
    
    updates = {}
    if payload.projectId is not None:
        updates["projectId"] = payload.projectId
    if payload.specId is not None:
        updates["specId"] = payload.specId
    if payload.kind is not None:
        updates["kind"] = payload.kind
    if payload.title is not None:
        updates["title"] = payload.title
    if payload.objective is not None:
        updates["objective"] = payload.objective
    if payload.steps is not None:
        updates["stepsJson"] = json.dumps(payload.steps)
    if payload.assertionHints is not None:
        updates["assertionHintsJson"] = json.dumps(payload.assertionHints)
    if payload.payload is not None:
        updates["payloadJson"] = json.dumps(payload.payload)
        logger.info(f"Saving payloadJson: {updates['payloadJson'][:500]}...")
    
    if updates:
        updated = test_cases.update_case(case_id, updates)
        if updated:
            logger.info(f"Updated case, new payload_json: {updated.get('payload_json', 'N/A')[:500]}...")
            for col in ("steps_json", "assertion_hints_json", "payload_json"):
                if col in updated and isinstance(updated[col], str):
                    updated[col] = json.loads(updated[col])
            return TestCase.model_validate(dict(updated))
    
    for col in ("steps_json", "assertion_hints_json", "payload_json"):
        if col in existing and isinstance(existing[col], str):
            existing[col] = json.loads(existing[col])
    return TestCase.model_validate(dict(existing))

@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case(
    case_id: str,
    _: dict = Depends(require_roles("admin", "tester")),
    test_cases: Any = Depends(get_test_cases),
) -> Response:
    existing = test_cases.get_case(case_id)
    if not existing:
        raise HTTPException(status_code=404, detail="测试用例不存在")
    
    test_cases.delete_case(case_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

from fastapi import APIRouter, Depends, Query, HTTPException, Response, status, Request
from typing import Any, Optional
from .deps import get_current_user, get_reporting, require_roles

router = APIRouter(prefix="/reports", tags=["reports"])

@router.get("/dashboard", response_model=dict[str, Any])
async def get_dashboard(
    projectId: Optional[str] = Query(None),
    _: dict = Depends(get_current_user),
    service: Any = Depends(get_reporting),
) -> dict[str, Any]:
    """
    Get testing dashboard statistics.
    """
    try:
        stats = service.get_dashboard_stats(project_id=projectId)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/run/{run_id}", response_model=dict[str, Any])
async def get_run_report(
    run_id: str,
    _: dict = Depends(get_current_user),
    service: Any = Depends(get_reporting),
) -> dict[str, Any]:
    """
    Get detailed report for a specific test run.
    """
    report = service.get_run_report(run_id)
    if not report:
        raise HTTPException(status_code=404, detail="Run report not found")
    return report


@router.get("/execution-summary", response_model=dict[str, Any])
async def get_execution_summary(
    projectId: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    runnerType: Optional[str] = Query(None),
    startDate: Optional[str] = Query(None),
    endDate: Optional[str] = Query(None),
    days: int = Query(10, ge=1, le=30),
    limit: int = Query(500, ge=1, le=2000),
    _: dict = Depends(get_current_user),
    service: Any = Depends(get_reporting),
) -> dict[str, Any]:
    try:
        return service.get_execution_summary(
            project_id=projectId,
            status=status,
            runner_type=runnerType,
            start_date=startDate,
            end_date=endDate,
            days=days,
            limit=limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/execution-summary/export")
async def export_execution_summary(
    projectId: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    runnerType: Optional[str] = Query(None),
    startDate: Optional[str] = Query(None),
    endDate: Optional[str] = Query(None),
    days: int = Query(10, ge=1, le=30),
    limit: int = Query(500, ge=1, le=2000),
    format: str = Query("json"),
    template: str = Query("weekly"),
    _: dict = Depends(get_current_user),
    service: Any = Depends(get_reporting),
):
    try:
        content, media_type, filename = service.export_execution_summary(
            project_id=projectId,
            status=status,
            runner_type=runnerType,
            start_date=startDate,
            end_date=endDate,
            days=days,
            limit=limit,
            format_name=format,
            template=template,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/runs", response_model=dict[str, Any])
async def list_run_reports(
    projectId: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    runnerType: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    _: dict = Depends(get_current_user),
    service: Any = Depends(get_reporting),
) -> dict[str, Any]:
    try:
        return service.list_run_reports(
            project_id=projectId,
            status=status,
            runner_type=runnerType,
            page=page,
            page_size=pageSize,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/run/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run_report(
    run_id: str,
    _: dict = Depends(require_roles("admin", "tester")),
    service: Any = Depends(get_reporting),
) -> Response:
    deleted = service.delete_run_report(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Run report not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/run/{run_id}/restore")
async def restore_run_report(
    run_id: str,
    _: dict = Depends(require_roles("admin", "tester")),
    service: Any = Depends(get_reporting),
) -> dict[str, Any]:
    restored = service.restore_run_report(run_id)
    if not restored:
        raise HTTPException(status_code=404, detail="Run report not found or not deleted")
    return {"restored": True, "id": run_id}


@router.post("/runs/batch-delete")
async def batch_delete_run_reports(
    request: Request,
    _: dict = Depends(require_roles("admin", "tester")),
    service: Any = Depends(get_reporting),
) -> dict[str, Any]:
    import json
    body = json.loads(await request.body())
    run_ids = body.get("runIds") or body.get("ids") or []
    if not isinstance(run_ids, list) or not run_ids:
        raise HTTPException(status_code=400, detail="runIds is required")
    deleted = service.batch_delete_run_reports([str(item).strip() for item in run_ids if str(item).strip()])
    return {"deleted": deleted}

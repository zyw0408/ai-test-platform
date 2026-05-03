from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from .deps import (
    get_api_testing,
    get_audit,
    get_current_user,
    get_security_finding,
    get_security_testing,
    require_roles,
)
from app.models import ApiRequestPublic, SecurityScanRequest, SecurityScanResult

router = APIRouter(prefix="/security", tags=["security"])


def _sse_event(payload: dict[str, Any], event: str = "message") -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

def _build_scan_audit_payload(
    *,
    target_collection_ids: list[str],
    target_url: str | None,
    payload: SecurityScanRequest,
    result: SecurityScanResult,
    request_count: int,
) -> dict[str, Any]:
    return {
        "collectionIds": target_collection_ids,
        "targetUrl": target_url,
        "targetMode": "url" if target_url else "project",
        "scanTypes": payload.scanTypes,
        "deepScan": payload.deepScan,
        "scanId": result.scanId,
        "requestCount": request_count,
        "totalIssues": result.totalIssues,
        "criticalCount": result.criticalCount,
        "highCount": result.highCount,
        "mediumCount": result.mediumCount,
        "lowCount": result.lowCount,
    }


async def _collect_scan_requests(
    *,
    api_testing: Any,
    security_testing: Any,
    payload: SecurityScanRequest,
) -> tuple[list[str], list[ApiRequestPublic], str | None]:
    target_url = str(payload.targetUrl or "").strip()
    if target_url:
        try:
            normalized_url = security_testing.normalize_target_url(target_url)
            collection_requests = await security_testing.build_requests_from_target_url(
                normalized_url,
                max_discovered_urls=payload.maxDiscoveredUrls,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not collection_requests:
            raise HTTPException(status_code=400, detail="targetUrl 未发现可扫描目标")
        return [], collection_requests, normalized_url

    collections = api_testing.list_collections(project_id=payload.projectId)
    if not collections:
        raise HTTPException(status_code=404, detail="Project collections not found")
    collection_ids_in_project = {str(item.get("id") or "") for item in collections}
    collection_ids_in_project.discard("")
    if payload.collectionIds:
        requested_ids = {str(item).strip() for item in payload.collectionIds if str(item).strip()}
        invalid_ids = sorted(requested_ids - collection_ids_in_project)
        if invalid_ids:
            raise HTTPException(
                status_code=400,
                detail=f"collectionIds 包含无效集合: {', '.join(invalid_ids)}",
            )
        target_collection_ids = sorted(requested_ids)
    else:
        target_collection_ids = sorted(collection_ids_in_project)
    collection_requests: list[ApiRequestPublic] = []
    for collection_id in target_collection_ids:
        rows = api_testing.list_requests(collection_id=collection_id)
        for row in rows:
            if bool(row.get("isFolder")):
                continue
            collection_requests.append(ApiRequestPublic.model_validate(row))
    if not collection_requests:
        raise HTTPException(status_code=400, detail="No runnable requests in selected collections")
    return target_collection_ids, collection_requests, None


async def _postprocess_scan_result(
    *,
    security_finding: Any,
    current_user: dict,
    audit: Any,
    payload: SecurityScanRequest,
    target_collection_ids: list[str],
    target_url: str | None,
    collection_requests: list[ApiRequestPublic],
    result: SecurityScanResult,
) -> SecurityScanResult:
    finding_map = security_finding.upsert_from_scan(
        project_id=payload.projectId,
        scan_id=result.scanId,
        vulnerabilities=result.vulnerabilities,
    )
    for item in result.vulnerabilities:
        signature = security_finding.make_signature(item)
        finding = finding_map.get(signature)
        if finding:
            item.findingId = finding.get("id")
    audit.log(
        actor_id=current_user["id"],
        action="security.scan.run",
        target_type="project",
        target_id=payload.projectId,
        payload=_build_scan_audit_payload(
            target_collection_ids=target_collection_ids,
            target_url=target_url,
            payload=payload,
            result=result,
            request_count=len(collection_requests),
        ),
    )
    return result


@router.post("/scan", response_model=SecurityScanResult)
async def run_security_scan(
    payload: SecurityScanRequest,
    current_user: dict = Depends(require_roles("admin", "tester")),
    api_testing: Any = Depends(get_api_testing),
    security_testing: Any = Depends(get_security_testing),
    security_finding: Any = Depends(get_security_finding),
    audit: Any = Depends(get_audit),
    _: dict = Depends(get_current_user),
) -> SecurityScanResult:
    target_collection_ids, collection_requests, target_url = await _collect_scan_requests(
        api_testing=api_testing,
        security_testing=security_testing,
        payload=payload,
    )

    result = await security_testing.run_security_scan(
        request=payload,
        collection_requests=collection_requests,
        env=None,
    )
    result = await _postprocess_scan_result(
        security_finding=security_finding,
        current_user=current_user,
        audit=audit,
        payload=payload,
        target_collection_ids=target_collection_ids,
        target_url=target_url,
        collection_requests=collection_requests,
        result=result,
    )
    return result


@router.post("/scan/start")
async def start_security_scan_task(
    payload: SecurityScanRequest,
    current_user: dict = Depends(require_roles("admin", "tester")),
    api_testing: Any = Depends(get_api_testing),
    security_testing: Any = Depends(get_security_testing),
    security_finding: Any = Depends(get_security_finding),
    audit: Any = Depends(get_audit),
    _: dict = Depends(get_current_user),
):
    target_collection_ids, collection_requests, target_url = await _collect_scan_requests(
        api_testing=api_testing,
        security_testing=security_testing,
        payload=payload,
    )

    async def _on_completed(result: SecurityScanResult) -> SecurityScanResult:
        return await _postprocess_scan_result(
            security_finding=security_finding,
            current_user=current_user,
            audit=audit,
            payload=payload,
            target_collection_ids=target_collection_ids,
            target_url=target_url,
            collection_requests=collection_requests,
            result=result,
        )

    task = await security_testing.start_scan_task(
        request=payload,
        collection_requests=collection_requests,
        env=None,
        on_completed=_on_completed,
    )
    audit.log(
        actor_id=current_user["id"],
        action="security.scan.start",
        target_type="project",
        target_id=payload.projectId,
        payload={
            "taskId": task.get("taskId"),
            "collectionIds": target_collection_ids,
            "targetUrl": target_url,
            "targetMode": "url" if target_url else "project",
            "scanTypes": payload.scanTypes,
            "deepScan": payload.deepScan,
            "requestCount": len(collection_requests),
        },
    )
    return task


@router.get("/scan/tasks/{task_id}")
async def get_security_scan_task(
    task_id: str,
    security_testing: Any = Depends(get_security_testing),
    _: dict = Depends(get_current_user),
):
    task = await security_testing.get_scan_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="scan task not found")
    return task


@router.get("/scan/tasks/{task_id}/events")
async def stream_security_scan_task(
    task_id: str,
    security_testing: Any = Depends(get_security_testing),
    _: dict = Depends(get_current_user),
):
    async def event_generator():
        while True:
            task = await security_testing.get_scan_task(task_id)
            if not task:
                yield _sse_event({"ok": False, "error": "scan task not found", "taskId": task_id}, "error")
                break
            yield _sse_event(task, "status")
            status_value = str(task.get("status") or "").lower()
            if status_value in {"completed", "failed", "cancelled"}:
                yield _sse_event({"ok": True, "taskId": task_id, "status": status_value}, "done")
                break
            await asyncio.sleep(1.2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/scan/tasks/{task_id}/cancel")
async def cancel_security_scan_task(
    task_id: str,
    current_user: dict = Depends(require_roles("admin", "tester")),
    security_testing: Any = Depends(get_security_testing),
    audit: Any = Depends(get_audit),
):
    task = await security_testing.cancel_scan_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="scan task not found")
    audit.log(
        actor_id=current_user["id"],
        action="security.scan.cancel",
        target_type="security_scan_task",
        target_id=task_id,
        payload={"status": task.get("status")},
    )
    return task


@router.get("/scans")
async def list_security_scans(
    projectId: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    audit: Any = Depends(get_audit),
    _: dict = Depends(get_current_user),
):
    logs = audit.list_logs(
        target_type="project",
        target_id=projectId,
        action_prefix="security.scan.run",
        limit=limit,
    )
    items: list[dict[str, Any]] = []
    for row in logs:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        items.append(
            {
                "id": row.get("id"),
                "projectId": row.get("targetId"),
                "scanId": payload.get("scanId"),
                "totalIssues": int(payload.get("totalIssues") or 0),
                "criticalCount": int(payload.get("criticalCount") or 0),
                "highCount": int(payload.get("highCount") or 0),
                "mediumCount": int(payload.get("mediumCount") or 0),
                "lowCount": int(payload.get("lowCount") or 0),
                "requestCount": int(payload.get("requestCount") or 0),
                "targetUrl": payload.get("targetUrl"),
                "targetMode": payload.get("targetMode") or ("url" if payload.get("targetUrl") else "project"),
                "scanTypes": payload.get("scanTypes") if isinstance(payload.get("scanTypes"), list) else [],
                "deepScan": bool(payload.get("deepScan", False)),
                "createdBy": row.get("actorId"),
                "createdAt": row.get("createdAt"),
            }
        )
    return {"items": items}


@router.delete("/scans/{scan_id}", status_code=204)
async def delete_security_scan(
    scan_id: str,
    current_user: dict = Depends(require_roles("admin", "tester")),
    audit: Any = Depends(get_audit),
    _: dict = Depends(get_current_user),
):
    logs = audit.list_logs(action_prefix="security.scan.run", limit=1000)
    target = next(
        (
            row
            for row in logs
            if str(row.get("id") or "") == scan_id
            or str((row.get("payload") or {}).get("scanId") or "") == scan_id
        ),
        None,
    )
    if not target:
        raise HTTPException(status_code=404, detail="scan report not found")
    deleted = audit.delete_log(str(target.get("id") or ""))
    if not deleted:
        raise HTTPException(status_code=404, detail="scan report not found")
    audit.log(
        actor_id=current_user["id"],
        action="security.scan.delete",
        target_type="security_scan_report",
        target_id=scan_id,
        payload={"deletedAuditId": str(target.get("id") or "")},
    )
    return None


@router.get("/findings")
async def list_security_findings(
    projectId: str = Query(...),
    status: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    security_finding: Any = Depends(get_security_finding),
    _: dict = Depends(get_current_user),
):
    rows = security_finding.list_findings(
        project_id=projectId,
        status=status,
        severity=severity,
        limit=limit,
    )
    return {"items": rows}


@router.patch("/findings/{finding_id}")
async def update_security_finding_status(
    finding_id: str,
    payload: dict,
    current_user: dict = Depends(require_roles("admin", "tester")),
    security_finding: Any = Depends(get_security_finding),
    audit: Any = Depends(get_audit),
):
    status_value = str(payload.get("status") or "").strip().lower()
    try:
        updated = security_finding.update_status(finding_id=finding_id, status=status_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not updated:
        raise HTTPException(status_code=404, detail="finding not found")
    audit.log(
        actor_id=current_user["id"],
        action="security.finding.status.update",
        target_type="security_finding",
        target_id=finding_id,
        payload={"status": status_value},
    )
    return updated

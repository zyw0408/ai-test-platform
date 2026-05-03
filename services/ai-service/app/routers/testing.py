import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, status, Response, File, UploadFile, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import List, Optional
from .deps import (
    get_current_user, 
    require_roles, 
    get_api_testing, 
    get_performance_testing, 
    get_audit,
    get_automation,
    get_reporting,
    get_test_cases,
    get_test_runs
)
from ..models import (
    ApiCollectionPublic, 
    ApiCollectionCreateRequest,
    ApiCollectionUpdateRequest,
    ApiRequestPublic,
    ApiRequestCreateRequest,
    ApiRequestUpdateRequest,
    ApiEnvironmentPublic, 
    ApiEnvironmentCreateRequest,
    ApiEnvironmentUpdateRequest,
    ApiRequestRunPublic,
    PerformanceRunRequest,
    PerformanceRunResult,
    TestRun,
    TestRunCreateRequest,
    TestCase
)
import logging
from typing import Any

router = APIRouter(prefix="/testing", tags=["testing"])
runs_router = APIRouter(prefix="/runs", tags=["runs"])
logger = logging.getLogger(__name__)


def _sse_event(payload: dict[str, Any], event: str = "message") -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _prepare_test_case_payload(case_data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(case_data)
    for col in ("steps_json", "assertion_hints_json", "payload_json"):
        value = normalized.get(col)
        if isinstance(value, str):
            try:
                normalized[col] = json.loads(value)
            except json.JSONDecodeError:
                normalized[col] = [] if col != "payload_json" else {}
        elif value is None:
            normalized[col] = [] if col != "payload_json" else {}
    return normalized

# --- Collections ---

@router.get("/collections", response_model=List[ApiCollectionPublic])
async def list_collections(
    projectId: str | None = Query(None),
    _: dict = Depends(get_current_user),
    api_testing: Any = Depends(get_api_testing),
) -> List[ApiCollectionPublic]:
    rows = api_testing.list_collections(project_id=projectId)
    return [ApiCollectionPublic.model_validate(item) for item in rows]

@router.post("/collections", response_model=ApiCollectionPublic)
async def create_collection(
    payload: ApiCollectionCreateRequest,
    current_user: dict = Depends(require_roles("admin", "tester")),
    api_testing: Any = Depends(get_api_testing),
) -> ApiCollectionPublic:
    try:
        created = api_testing.create_collection(
            project_id=payload.projectId,
            name=payload.name,
            description=payload.description,
            variables=payload.variables,
            created_by=current_user["id"]
        )
        return ApiCollectionPublic.model_validate(created)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("/collections/{collection_id}", response_model=ApiCollectionPublic)
async def get_collection(
    collection_id: str,
    _: dict = Depends(get_current_user),
    api_testing: Any = Depends(get_api_testing),
) -> ApiCollectionPublic:
    row = api_testing.get_collection(collection_id)
    if not row:
        raise HTTPException(status_code=404, detail="Collection not found")
    return ApiCollectionPublic.model_validate(row)

@router.patch("/collections/{collection_id}", response_model=ApiCollectionPublic)
async def update_collection(
    collection_id: str,
    payload: ApiCollectionUpdateRequest,
    current_user: dict = Depends(require_roles("admin", "tester")),
    api_testing: Any = Depends(get_api_testing),
) -> ApiCollectionPublic:
    try:
        updated = api_testing.update_collection(
            collection_id=collection_id,
            updates=payload.model_dump(exclude_unset=True)
        )
        return ApiCollectionPublic.model_validate(updated)
    except KeyError:
        raise HTTPException(status_code=404, detail="Collection not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: str,
    current_user: dict = Depends(require_roles("admin", "tester")),
    api_testing: Any = Depends(get_api_testing),
):
    success = api_testing.delete_collection(collection_id)
    if not success:
        raise HTTPException(status_code=404, detail="Collection not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# --- Requests ---

@router.get("/requests", response_model=List[ApiRequestPublic])
async def list_requests(
    collectionId: str = Query(...),
    api_testing: Any = Depends(get_api_testing),
    _: dict = Depends(get_current_user),
) -> List[ApiRequestPublic]:
    rows = api_testing.list_requests(collection_id=collectionId)
    return [ApiRequestPublic.model_validate(item) for item in rows]

@router.post("/requests", response_model=ApiRequestPublic)
async def create_request(
    payload: ApiRequestCreateRequest,
    current_user: dict = Depends(require_roles("admin", "tester")),
    api_testing: Any = Depends(get_api_testing),
) -> ApiRequestPublic:
    try:
        created = api_testing.create_request(
            payload=payload.model_dump(),
            created_by=current_user["id"]
        )
        return ApiRequestPublic.model_validate(created)
    except KeyError:
        raise HTTPException(status_code=404, detail="Collection not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.patch("/requests/{request_id}", response_model=ApiRequestPublic)
async def update_request(
    request_id: str,
    payload: ApiRequestUpdateRequest,
    current_user: dict = Depends(require_roles("admin", "tester")),
    api_testing: Any = Depends(get_api_testing),
) -> ApiRequestPublic:
    try:
        updated = api_testing.update_request(
            request_id=request_id,
            updates=payload.model_dump(exclude_unset=True)
        )
        return ApiRequestPublic.model_validate(updated)
    except KeyError:
        raise HTTPException(status_code=404, detail="Request not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.delete("/requests/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_request(
    request_id: str,
    current_user: dict = Depends(require_roles("admin", "tester")),
    api_testing: Any = Depends(get_api_testing),
):
    success = api_testing.delete_request(request_id)
    if not success:
        raise HTTPException(status_code=404, detail="Request not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# --- Environments ---

@router.get("/environments", response_model=List[ApiEnvironmentPublic])
async def list_environments(
    collectionId: str = Query(...),
    api_testing: Any = Depends(get_api_testing),
    _: dict = Depends(get_current_user),
) -> List[ApiEnvironmentPublic]:
    rows = api_testing.list_environments(collection_id=collectionId)
    return [ApiEnvironmentPublic.model_validate(item) for item in rows]

@router.post("/environments", response_model=ApiEnvironmentPublic)
async def create_environment(
    payload: ApiEnvironmentCreateRequest,
    current_user: dict = Depends(require_roles("admin", "tester")),
    api_testing: Any = Depends(get_api_testing),
) -> ApiEnvironmentPublic:
    try:
        created = api_testing.create_environment(
            collection_id=payload.collectionId,
            name=payload.name,
            variables=payload.variables,
            is_default=payload.isDefault,
            created_by=current_user["id"]
        )
        return ApiEnvironmentPublic.model_validate(created)
    except KeyError:
        raise HTTPException(status_code=404, detail="Collection not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.patch("/environments/{env_id}", response_model=ApiEnvironmentPublic)
async def update_environment(
    env_id: str,
    payload: ApiEnvironmentUpdateRequest,
    current_user: dict = Depends(require_roles("admin", "tester")),
    api_testing: Any = Depends(get_api_testing),
) -> ApiEnvironmentPublic:
    try:
        updated = api_testing.update_environment(
            environment_id=env_id,
            updates=payload.model_dump(exclude_unset=True)
        )
        return ApiEnvironmentPublic.model_validate(updated)
    except KeyError:
        raise HTTPException(status_code=404, detail="Environment not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.delete("/environments/{env_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(
    env_id: str,
    current_user: dict = Depends(require_roles("admin", "tester")),
    api_testing: Any = Depends(get_api_testing),
):
    success = api_testing.delete_environment(env_id)
    if not success:
        raise HTTPException(status_code=404, detail="Environment not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# --- Performance & Stats ---

@router.post("/performance/run", response_model=PerformanceRunResult)
async def run_performance_test(
    payload: PerformanceRunRequest,
    current_user: dict = Depends(get_current_user),
    audit = Depends(get_audit),
    api_testing = Depends(get_api_testing),
    perf_testing = Depends(get_performance_testing),
) -> PerformanceRunResult:
    try:
        collection = api_testing.get_collection(payload.collectionId)
        requests_raw = api_testing.list_requests(payload.collectionId)
        requests = [ApiRequestPublic.model_validate(r) for r in requests_raw]
        
        env = None
        if payload.environmentId:
            env_raw = api_testing.get_environment(payload.environmentId)
            env = ApiEnvironmentPublic.model_validate(env_raw)

        result = await perf_testing.run_load_test(
            request=payload,
            requests=requests,
            env=env
        )

        audit.log(
            actor_id=current_user["id"],
            action="performance.run",
            target_type="api_collection",
            target_id=payload.collectionId,
            payload={
                "vus": payload.vus,
                "duration": payload.durationSeconds,
                "tps": result.tps,
                "p95": result.p95LatencyMs
            },
        )
        return result
    except Exception as exc:
        logger.exception("performance test failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/performance/runs")
async def start_performance_run(
    payload: PerformanceRunRequest,
    current_user: dict = Depends(get_current_user),
    api_testing: Any = Depends(get_api_testing),
    perf_testing: Any = Depends(get_performance_testing),
):
    try:
        collection = api_testing.get_collection(payload.collectionId)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")

        rows = api_testing.list_requests(payload.collectionId)
        if payload.requestIds:
            selected_ids = {str(item) for item in payload.requestIds}
            rows = [row for row in rows if str(row.get("id")) in selected_ids]
        rows = [row for row in rows if not bool(row.get("isFolder"))]
        if not rows:
            raise HTTPException(status_code=400, detail="No runnable requests selected")
        requests = [ApiRequestPublic.model_validate(row) for row in rows]

        env = None
        if payload.environmentId:
            env_raw = api_testing.get_environment(payload.environmentId)
            if not env_raw:
                raise HTTPException(status_code=404, detail="Environment not found")
            env = ApiEnvironmentPublic.model_validate(env_raw)

        return await perf_testing.start_run(
            request=payload,
            requests=requests,
            env=env,
            created_by=current_user.get("id"),
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("failed to start performance run")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/performance/runs")
async def list_performance_runs(
    projectId: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    perf_testing: Any = Depends(get_performance_testing),
    _: dict = Depends(get_current_user),
):
    return perf_testing.list_runs(project_id=projectId, limit=limit)


@router.get("/performance/capacity")
async def get_performance_capacity(
    perf_testing: Any = Depends(get_performance_testing),
    _: dict = Depends(get_current_user),
):
    return perf_testing.get_capacity()


@router.get("/performance/regression-config")
async def get_performance_regression_config(
    perf_testing: Any = Depends(get_performance_testing),
    _: dict = Depends(get_current_user),
):
    return perf_testing.get_regression_config()


@router.patch("/performance/regression-config")
async def update_performance_regression_config(
    payload: dict,
    perf_testing: Any = Depends(get_performance_testing),
    _: dict = Depends(require_roles("admin", "tester")),
):
    return perf_testing.update_regression_config(
        max_p95_delta_ms=payload.get("maxP95DeltaMs"),
        max_error_rate_delta=payload.get("maxErrorRateDelta"),
        min_tps_delta=payload.get("minTpsDelta"),
    )


@router.get("/performance/compare")
async def compare_performance_runs(
    projectId: str | None = Query(None),
    collectionId: str | None = Query(None),
    limit: int = Query(20, ge=2, le=100),
    perf_testing: Any = Depends(get_performance_testing),
    _: dict = Depends(get_current_user),
):
    return perf_testing.compare_runs(project_id=projectId, collection_id=collectionId, limit=limit)


@router.get("/performance/runs/{run_id}")
async def get_performance_run(
    run_id: str,
    perf_testing: Any = Depends(get_performance_testing),
    _: dict = Depends(get_current_user),
):
    run = perf_testing.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Performance run not found")
    return run


@router.delete("/performance/runs/{run_id}")
async def stop_performance_run(
    run_id: str,
    perf_testing: Any = Depends(get_performance_testing),
    _: dict = Depends(require_roles("admin", "tester")),
):
    stopped = perf_testing.stop_run(run_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="Performance run not found or already finished")
    return {"ok": True, "id": run_id}


@router.get("/performance/runs/{run_id}/events")
async def stream_performance_run(
    run_id: str,
    perf_testing: Any = Depends(get_performance_testing),
    _: dict = Depends(get_current_user),
):
    async def event_generator():
        while True:
            run = perf_testing.get_run(run_id)
            if not run:
                yield _sse_event({"ok": False, "error": "Performance run not found", "id": run_id}, "error")
                break
            yield _sse_event(run, "status")
            if str(run.get("status") or "").lower() in {"completed", "failed", "cancelled"}:
                yield _sse_event({"ok": True, "id": run_id, "status": run.get("status")}, "done")
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


@router.get("/performance/runs/{run_id}/export")
async def export_performance_run(
    run_id: str,
    format: str = Query("json"),
    perf_testing: Any = Depends(get_performance_testing),
    _: dict = Depends(get_current_user),
):
    try:
        content, media_type, filename = perf_testing.export_run(run_id, format)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/performance/runs/{run_id}/record")
async def delete_performance_run_record(
    run_id: str,
    force: bool = Query(False),
    perf_testing: Any = Depends(get_performance_testing),
    _: dict = Depends(require_roles("admin", "tester")),
):
    try:
        deleted = perf_testing.delete_run_record(run_id, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Performance run not found")
    return {"ok": True, "id": run_id}


@router.post("/performance/runs/batch-delete")
async def batch_delete_performance_run_records(
    payload: dict,
    perf_testing: Any = Depends(get_performance_testing),
    _: dict = Depends(require_roles("admin", "tester")),
):
    run_ids = payload.get("runIds")
    if not isinstance(run_ids, list):
        raise HTTPException(status_code=400, detail="runIds must be a list")
    return perf_testing.batch_delete_run_records(
        run_ids=[str(item) for item in run_ids],
        force=bool(payload.get("force", False)),
    )

@router.get("/runs", response_model=List[TestRun])
async def list_generic_runs(
    projectId: str | None = Query(None),
    limit: int = Query(40, ge=1, le=100),
    test_runs: Any = Depends(get_test_runs),
    _: dict = Depends(get_current_user),
) -> List[TestRun]:
    rows = test_runs.list_runs(project_id=projectId, limit=limit)
    return [TestRun.model_validate(item) for item in rows]

@router.get("/stats")
async def get_testing_stats(
    projectId: str = Query(...),
    reporting: Any = Depends(get_reporting),
    _: dict = Depends(get_current_user),
):
    return reporting.get_project_stats(projectId)

@router.get("/runs/{run_id}")
async def get_run_full_report(
    run_id: str,
    reporting: Any = Depends(get_reporting),
    _: dict = Depends(get_current_user),
):
    report = reporting.get_run_report(run_id)
    if not report:
        raise HTTPException(status_code=404, detail="Run not found")
    return report

@router.get("/api-runs", response_model=List[ApiRequestRunPublic])
async def list_api_runs(
    collectionId: str | None = Query(None),
    requestId: str | None = Query(None),
    limit: int = Query(100, ge=1, le=300),
    api_testing = Depends(get_api_testing),
    _: dict = Depends(get_current_user),
) -> List[ApiRequestRunPublic]:
    rows = api_testing.list_runs(collection_id=collectionId, request_id=requestId, limit=limit)
    return [ApiRequestRunPublic.model_validate(item) for item in rows]

# --- Execution ---

@router.post("/requests/{request_id}/send", response_model=ApiRequestRunPublic)
async def send_request(
    request_id: str,
    payload: dict = {},
    current_user: dict = Depends(get_current_user),
    api_testing = Depends(get_api_testing),
) -> ApiRequestRunPublic:
    try:
        run = await api_testing.send_request(
            request_id=request_id,
            created_by=current_user["id"],
            environment_id=payload.get("environmentId"),
            variables=payload.get("variables"),
            timeout_ms=payload.get("timeoutMs", 15000),
            verify_ssl=payload.get("verifySsl", True),
            tls=payload.get("tls"),
        )
        return ApiRequestRunPublic.model_validate(run)
    except KeyError:
        raise HTTPException(status_code=404, detail="Request not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.post("/requests/{request_id}/send-batch")
async def send_batch_request(
    request_id: str,
    payload: dict = {},
    current_user: dict = Depends(get_current_user),
    api_testing = Depends(get_api_testing),
):
    try:
        return await api_testing.send_request_batch(
            request_id=request_id,
            created_by=current_user["id"],
            environment_id=payload.get("environmentId"),
            variable_sets=payload.get("variableSets") or [],
            timeout_ms=payload.get("timeoutMs", 15000),
            verify_ssl=payload.get("verifySsl", True),
            tls=payload.get("tls"),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.post("/collections/{collection_id}/run")
async def run_collection(
    collection_id: str,
    payload: dict = {},
    current_user: dict = Depends(get_current_user),
    api_testing = Depends(get_api_testing),
):
    try:
        result = await api_testing.run_collection(
            collection_id=collection_id,
            created_by=current_user["id"],
            environment_id=payload.get("environmentId"),
            variables=payload.get("variables"),
            group_name=payload.get("groupName"),
            request_ids=payload.get("requestIds"),
            sequential=payload.get("sequential", False),
            timeout_ms=payload.get("timeoutMs", 15000),
            verify_ssl=payload.get("verifySsl", True),
            tls=payload.get("tls"),
        )
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail="Collection not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.post("/collections/{collection_id}/import-openapi")
async def import_openapi(
    collection_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_roles("admin", "tester")),
    api_testing: Any = Depends(get_api_testing),
):
    try:
        content = await file.read()
        source_text = content.decode("utf-8")
        result = api_testing.import_openapi(
            collection_id=collection_id,
            source_text=source_text,
            created_by=current_user["id"]
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("/collections/{collection_id}/export-postman")
async def export_postman(
    collection_id: str,
    api_testing: Any = Depends(get_api_testing),
    _: dict = Depends(get_current_user),
):
    try:
        return api_testing.export_postman_collection(collection_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Collection not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- Runs Router (for /runs endpoint) ---

@runs_router.post("", response_model=TestRun, status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: TestRunCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_roles("admin", "tester")),
    test_runs: Any = Depends(get_test_runs),
    test_cases: Any = Depends(get_test_cases),
    automation: Any = Depends(get_automation),
) -> TestRun:
    case_data = test_cases.get_case(payload.caseId)
    if not case_data:
        raise HTTPException(status_code=404, detail="测试用例不存在")
    
    test_case = TestCase.model_validate(_prepare_test_case_payload(case_data))
    
    run_data = test_runs.create_run_with_params(
        case_id=payload.caseId,
        project_id=payload.projectId,
        runner_type=payload.runnerType,
        triggered_by=current_user["id"],
        sequential=payload.sequential,
    )
    run = TestRun.model_validate(run_data)
    
    background_tasks.add_task(
        _execute_run_background,
        run.id,
        test_case,
        automation,
    )
    
    return run


async def _execute_run_background(run_id: str, test_case: TestCase, automation: Any):
    logger.info(f"Starting background execution for run {run_id}, case {test_case.id}")
    logger.info(f"Test case payload: {test_case.payload}")
    try:
        result = await automation.execute_run(run_id, test_case)
        logger.info(f"Background execution completed for run {run_id}: {result}")
    except Exception as e:
        logger.exception(f"Background execution failed for run {run_id}: {e}")


@runs_router.get("", response_model=List[TestRun])
async def list_runs(
    projectId: str | None = Query(None),
    limit: int = Query(40, ge=1, le=100),
    test_runs: Any = Depends(get_test_runs),
    _: dict = Depends(get_current_user),
) -> List[TestRun]:
    rows = test_runs.list_runs(project_id=projectId, limit=limit)
    return [TestRun.model_validate(item) for item in rows]


@runs_router.get("/{run_id}", response_model=TestRun)
async def get_run(
    run_id: str,
    test_runs: Any = Depends(get_test_runs),
    _: dict = Depends(get_current_user),
) -> TestRun:
    run_data = test_runs.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return TestRun.model_validate(run_data)


@runs_router.get("/{run_id}/events")
async def stream_run_events(
    run_id: str,
    test_runs: Any = Depends(get_test_runs),
    _: dict = Depends(get_current_user),
):
    async def event_generator():
        while True:
            run_data = test_runs.get_run(run_id)
            if not run_data:
                yield _sse_event({"ok": False, "error": "运行记录不存在", "id": run_id}, "error")
                break

            run = TestRun.model_validate(run_data)
            payload = run.model_dump()
            yield _sse_event(payload, "status")

            current_status = str(run.status or "").lower()
            if current_status in {"passed", "failed", "cancelled"}:
                yield _sse_event({"ok": True, "id": run_id, "status": run.status}, "done")
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


@runs_router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    run_id: str,
    _: dict = Depends(require_roles("admin", "tester")),
    test_runs: Any = Depends(get_test_runs),
) -> Response:
    deleted = test_runs.delete_run(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@runs_router.post("/batch-delete")
async def batch_delete_runs(
    payload: dict[str, Any],
    _: dict = Depends(require_roles("admin", "tester")),
    test_runs: Any = Depends(get_test_runs),
) -> dict[str, Any]:
    run_ids = payload.get("runIds") or payload.get("ids") or []
    if not isinstance(run_ids, list) or not run_ids:
        raise HTTPException(status_code=400, detail="runIds is required")
    normalized_ids = [str(item).strip() for item in run_ids if str(item).strip()]
    if not normalized_ids:
        raise HTTPException(status_code=400, detail="runIds is required")
    return test_runs.batch_delete_runs(normalized_ids)

from __future__ import annotations

import asyncio
import contextlib
import csv
from collections import deque
import io
import json
import statistics
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.models import (
    ApiEnvironmentPublic,
    ApiRequestPublic,
    PerformancePoint,
    PerformanceRunRequest,
    PerformanceRunResult,
    new_id,
    utc_now,
)
from app.services.api_testing import ApiTestingService
from app.store import JsonStore

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class PerformanceTestingService:
    def __init__(
        self,
        api_testing_service: ApiTestingService,
        store: JsonStore,
        artifacts_dir: Path,
        max_concurrent_runs: int = 2,
        max_queue_size: int = 20,
        project_max_concurrent_runs: int = 1,
        project_max_queue_size: int = 5,
        regression_max_p95_delta_ms: float = 100,
        regression_max_error_rate_delta: float = 0.02,
        regression_min_tps_delta: float = -5.0,
    ):
        self._api_service = api_testing_service
        self._store = store
        self._artifacts_dir = artifacts_dir
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._max_concurrent_runs = max(1, int(max_concurrent_runs))
        self._max_queue_size = max(0, int(max_queue_size))
        self._project_max_concurrent_runs = max(1, int(project_max_concurrent_runs))
        self._project_max_queue_size = max(0, int(project_max_queue_size))
        self._regression_max_p95_delta_ms = float(regression_max_p95_delta_ms)
        self._regression_max_error_rate_delta = float(regression_max_error_rate_delta)
        self._regression_min_tps_delta = float(regression_min_tps_delta)
        self._pending_runs: deque[dict[str, Any]] = deque()
        self._running_run_ids: set[str] = set()
        self._scheduler_lock = asyncio.Lock()

    async def aclose(self) -> None:
        for task in list(self._tasks.values()):
            if not task.done():
                task.cancel()
        for task in list(self._tasks.values()):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        self._pending_runs.clear()
        self._running_run_ids.clear()

    async def run_load_test(
        self,
        request: PerformanceRunRequest,
        requests: list[ApiRequestPublic],
        env: ApiEnvironmentPublic | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> PerformanceRunResult:
        run_id = f"perf-{int(time.time())}"
        start_time = time.time()
        end_time = start_time + request.durationSeconds

        csv_variables = self._load_csv_variables(request.dataFileUri)
        results_latencies: list[float] = []
        results_failed = 0
        time_series: list[PerformancePoint] = []
        counter_lock = asyncio.Lock()
        rate_lock = asyncio.Lock()
        next_slot_time = time.monotonic()

        window_passed = 0
        window_failed = 0
        window_latencies: list[float] = []

        async def report_progress() -> None:
            if not progress_callback:
                return
            total = len(results_latencies) + results_failed
            elapsed = max(time.time() - start_time, 0.001)
            payload = {
                "elapsedSeconds": int(elapsed),
                "totalRequests": total,
                "successCount": len(results_latencies),
                "failCount": results_failed,
                "tps": round(total / elapsed, 2),
                "errorRate": round((results_failed / total), 4) if total else 0.0,
                "seriesPoints": len(time_series),
            }
            maybe_awaitable = progress_callback(payload)
            if asyncio.iscoroutine(maybe_awaitable):
                await maybe_awaitable

        async def monitor():
            nonlocal window_passed, window_failed, window_latencies
            while time.time() < end_time:
                win_start = time.time()
                await asyncio.sleep(1.0)
                win_end = time.time()

                async with counter_lock:
                    total = window_passed + window_failed
                    if total > 0:
                        tps = total / max(win_end - win_start, 0.001)
                        avg_lat = statistics.mean(window_latencies) if window_latencies else 0.0
                        err_rate = window_failed / total
                        time_series.append(
                            PerformancePoint(
                                timestamp=round(win_end - start_time, 1),
                                tps=round(tps, 2),
                                latencyMs=round(avg_lat, 2),
                                errorRate=round(err_rate, 4),
                            )
                        )
                    window_passed = 0
                    window_failed = 0
                    window_latencies = []
                await report_progress()

        async def acquire_rate_slot():
            nonlocal next_slot_time
            if not request.targetTps:
                return
            interval = 1.0 / float(request.targetTps)
            async with rate_lock:
                now_mono = time.monotonic()
                wait_seconds = max(0.0, next_slot_time - now_mono)
                next_slot_time = max(now_mono, next_slot_time) + interval
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

        async def worker(worker_id: int):
            nonlocal results_failed, window_passed, window_failed, window_latencies
            if request.rampUpSeconds > 0:
                delay = (worker_id / max(request.vus, 1)) * request.rampUpSeconds
                await asyncio.sleep(delay)

            iteration = 0
            while time.time() < end_time:
                current_data_vars: dict[str, str] = {}
                if csv_variables:
                    data_idx = (worker_id + iteration) % len(csv_variables)
                    current_data_vars = csv_variables[data_idx]

                for req_meta in requests:
                    if time.time() >= end_time:
                        break
                    await acquire_rate_slot()
                    req_start = time.time()
                    try:
                        res = await self._api_service.run_request(
                            req_meta,
                            env,
                            current_data_vars,
                            timeout_ms=request.timeoutMs,
                            verify_ssl=request.verifySsl,
                            tls=request.tls,
                        )
                        latency = (time.time() - req_start) * 1000
                        async with counter_lock:
                            if res.success:
                                results_latencies.append(latency)
                                window_passed += 1
                                window_latencies.append(latency)
                            else:
                                results_failed += 1
                                window_failed += 1
                    except Exception:
                        async with counter_lock:
                            results_failed += 1
                            window_failed += 1
                iteration += 1

        worker_tasks = [asyncio.create_task(worker(i)) for i in range(request.vus)]
        monitor_task = asyncio.create_task(monitor())
        await asyncio.gather(*worker_tasks)
        monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor_task
        await report_progress()

        total_success = len(results_latencies)
        total_requests = total_success + results_failed
        elapsed = max(time.time() - start_time, 0.001)
        overall_tps = round(total_requests / elapsed, 2)

        if not results_latencies:
            return PerformanceRunResult(
                runId=run_id,
                totalRequests=total_requests,
                successCount=0,
                failCount=results_failed,
                avgLatencyMs=0,
                p95LatencyMs=0,
                p99LatencyMs=0,
                maxLatencyMs=0,
                tps=overall_tps,
                timeSeries=time_series,
                status="completed",
                passedSla=False,
                errorMsg="No successful requests recorded.",
            )

        results_latencies.sort()
        count = len(results_latencies)

        def percentile(values: list[float], p: float) -> float:
            if not values:
                return 0.0
            idx = max(0, min(len(values) - 1, int(round((len(values) - 1) * p))))
            return values[idx]

        p95_lat = percentile(results_latencies, 0.95)
        p99_lat = percentile(results_latencies, 0.99)
        actual_err_rate = results_failed / total_requests if total_requests > 0 else 0

        passed_sla = True
        errors: list[str] = []
        if request.slaMaxP95Latency and p95_lat > request.slaMaxP95Latency:
            passed_sla = False
            errors.append(
                f"P95 {p95_lat:.1f}ms 超过阈值 {request.slaMaxP95Latency}ms"
            )
        if request.slaMaxErrorRate and actual_err_rate > request.slaMaxErrorRate:
            passed_sla = False
            errors.append(
                f"错误率 {actual_err_rate*100:.2f}% 超过阈值 {request.slaMaxErrorRate*100:.2f}%"
            )
        if request.targetTps and overall_tps < request.targetTps:
            passed_sla = False
            errors.append(f"实际 TPS {overall_tps} 低于目标 {request.targetTps}")

        return PerformanceRunResult(
            runId=run_id,
            totalRequests=total_requests,
            successCount=count,
            failCount=results_failed,
            avgLatencyMs=round(statistics.mean(results_latencies), 2),
            p95LatencyMs=round(p95_lat, 2),
            p99LatencyMs=round(p99_lat, 2),
            maxLatencyMs=round(max(results_latencies), 2),
            tps=overall_tps,
            timeSeries=time_series,
            status="completed",
            passedSla=passed_sla,
            errorMsg="; ".join(errors) if errors else None,
        )

    async def start_run(
        self,
        *,
        request: PerformanceRunRequest,
        requests: list[ApiRequestPublic],
        env: ApiEnvironmentPublic | None,
        created_by: str | None,
    ) -> dict[str, Any]:
        queued_count = len(self._pending_runs)
        running_count = len(self._running_run_ids)
        if queued_count >= self._max_queue_size:
            raise ValueError(
                f"性能任务排队已满(queued={queued_count}, maxQueue={self._max_queue_size})，请稍后重试"
            )
        project_running = self._project_running_count(request.projectId)
        project_queued = self._project_queued_count(request.projectId)
        if project_running >= self._project_max_concurrent_runs and project_queued >= self._project_max_queue_size:
            raise ValueError(
                "当前项目性能任务配额已满"
                f"(running={project_running}/{self._project_max_concurrent_runs}, "
                f"queued={project_queued}/{self._project_max_queue_size})，请稍后重试"
            )
        if (
            project_queued >= self._project_max_queue_size
            and running_count >= self._max_concurrent_runs
        ):
            raise ValueError(
                "当前项目性能任务排队配额已满"
                f"(queued={project_queued}/{self._project_max_queue_size})，请稍后重试"
            )
        run_id = new_id("prun")
        now = utc_now()
        run = {
            "id": run_id,
            "projectId": request.projectId,
            "collectionId": request.collectionId,
            "environmentId": request.environmentId,
            "status": "queued",
            "createdBy": created_by,
            "createdAt": now,
            "updatedAt": now,
            "startedAt": None,
            "finishedAt": None,
            "profile": request.model_dump(),
            "progress": {
                "elapsedSeconds": 0,
                "totalRequests": 0,
                "successCount": 0,
                "failCount": 0,
                "tps": 0.0,
                "errorRate": 0.0,
                "seriesPoints": 0,
            },
            "queuePosition": max(queued_count, 0) + 1,
            "result": None,
            "errorMsg": None,
            "artifactIds": [],
            "logs": [
                "性能任务已创建，等待执行",
                f"capacity: running={running_count}/{self._max_concurrent_runs}, queued={queued_count}/{self._max_queue_size}",
                f"project-capacity: running={project_running}/{self._project_max_concurrent_runs}, queued={project_queued}/{self._project_max_queue_size}",
            ],
        }
        self._store.insert("performance_runs", run)
        self._pending_runs.append(
            {
                "run_id": run_id,
                "project_id": request.projectId,
                "request": request,
                "requests": requests,
                "env": env,
            }
        )
        await self._schedule_runs()
        return run

    def list_runs(self, project_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if project_id:
            return self._store.list_by_json_field(
                "performance_runs",
                field_name="projectId",
                field_value=project_id,
                sort_by="created_at",
                sort_order="desc",
                limit=max(min(limit, 200), 1),
            )
        return self._store.list_all(
            "performance_runs",
            sort_by="created_at",
            sort_order="desc",
            limit=max(min(limit, 200), 1),
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self._store.get("performance_runs", run_id)

    def get_capacity(self) -> dict[str, int]:
        return {
            "maxConcurrentRuns": self._max_concurrent_runs,
            "maxQueueSize": self._max_queue_size,
            "projectMaxConcurrentRuns": self._project_max_concurrent_runs,
            "projectMaxQueueSize": self._project_max_queue_size,
            "running": len(self._running_run_ids),
            "queued": len(self._pending_runs),
        }

    def get_regression_config(self) -> dict[str, float]:
        return {
            "maxP95DeltaMs": self._regression_max_p95_delta_ms,
            "maxErrorRateDelta": self._regression_max_error_rate_delta,
            "minTpsDelta": self._regression_min_tps_delta,
        }

    def update_regression_config(
        self,
        *,
        max_p95_delta_ms: float | None = None,
        max_error_rate_delta: float | None = None,
        min_tps_delta: float | None = None,
    ) -> dict[str, float]:
        if max_p95_delta_ms is not None:
            self._regression_max_p95_delta_ms = float(max_p95_delta_ms)
        if max_error_rate_delta is not None:
            self._regression_max_error_rate_delta = float(max_error_rate_delta)
        if min_tps_delta is not None:
            self._regression_min_tps_delta = float(min_tps_delta)
        return self.get_regression_config()

    def delete_run_record(self, run_id: str, *, force: bool = False) -> bool:
        run = self.get_run(run_id)
        if not run:
            return False
        status = str(run.get("status") or "")
        if status in {"queued", "starting", "running"} and not force:
            raise ValueError("运行中或排队中的任务不能直接删除，请先停止任务")
        if force and status in {"queued", "starting", "running"}:
            self.stop_run(run_id)
        deleted = self._store.soft_delete("performance_runs", run_id)
        return bool(deleted)

    def batch_delete_run_records(
        self,
        run_ids: list[str],
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        deleted_ids: list[str] = []
        skipped: list[dict[str, str]] = []
        for run_id in [str(item).strip() for item in run_ids if str(item).strip()]:
            try:
                ok = self.delete_run_record(run_id, force=force)
            except ValueError as exc:
                skipped.append({"id": run_id, "reason": str(exc)})
                continue
            if ok:
                deleted_ids.append(run_id)
            else:
                skipped.append({"id": run_id, "reason": "not_found"})
        return {
            "deletedCount": len(deleted_ids),
            "deletedIds": deleted_ids,
            "skipped": skipped,
        }

    def export_run(self, run_id: str, format_name: str = "json") -> tuple[bytes, str, str]:
        run = self.get_run(run_id)
        if not run:
            raise KeyError(f"Performance run not found: {run_id}")
        fmt = str(format_name or "json").lower()
        if fmt == "json":
            payload = json.dumps(run, ensure_ascii=False, indent=2).encode("utf-8")
            return payload, "application/json; charset=utf-8", f"{run_id}.json"
        if fmt == "csv":
            return self._export_run_csv(run), "text/csv; charset=utf-8", f"{run_id}.csv"
        raise ValueError(f"Unsupported format: {format_name}")

    def compare_runs(
        self,
        *,
        project_id: str | None = None,
        collection_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        rows = self.list_runs(project_id=project_id, limit=max(min(limit, 100), 2))
        if collection_id:
            rows = [item for item in rows if str(item.get("collectionId")) == collection_id]
        completed = [
            item
            for item in rows
            if str(item.get("status")) == "completed"
            and isinstance(item.get("result"), dict)
        ]
        timeline: list[dict[str, Any]] = []
        for item in completed:
            result = item.get("result") or {}
            timeline.append(
                {
                    "runId": item.get("id"),
                    "createdAt": item.get("createdAt"),
                    "tps": float(result.get("tps", 0) or 0),
                    "p95LatencyMs": float(result.get("p95LatencyMs", 0) or 0),
                    "errorRate": (
                        float(result.get("failCount", 0) or 0)
                        / max(int(result.get("totalRequests", 0) or 0), 1)
                    ),
                }
            )
        latest = timeline[0] if timeline else None
        baseline = timeline[1] if len(timeline) > 1 else None
        deltas = None
        if latest and baseline:
            deltas = {
                "tpsDelta": round(latest["tps"] - baseline["tps"], 2),
                "p95DeltaMs": round(latest["p95LatencyMs"] - baseline["p95LatencyMs"], 2),
                "errorRateDelta": round(latest["errorRate"] - baseline["errorRate"], 6),
            }
        return {
            "latest": latest,
            "baseline": baseline,
            "deltas": deltas,
            "timeline": list(reversed(timeline)),
        }

    async def _schedule_runs(self) -> None:
        async with self._scheduler_lock:
            while self._pending_runs and len(self._running_run_ids) < self._max_concurrent_runs:
                pending = self._pick_next_schedulable_pending()
                if pending is None:
                    break
                run_id = str(pending["run_id"])
                self._running_run_ids.add(run_id)
                self._patch_run(
                    run_id,
                    {
                        "status": "starting",
                        "updatedAt": utc_now(),
                        "queuePosition": 0,
                        "logs": ["任务开始分配执行槽位"],
                    },
                )
                task = asyncio.create_task(
                    self._execute_run(
                        run_id=run_id,
                        request=pending["request"],
                        requests=pending["requests"],
                        env=pending["env"],
                    )
                )
                self._tasks[run_id] = task
                task.add_done_callback(lambda _, rid=run_id: self._on_run_finished(rid))
            self._refresh_queue_positions()

    def _pick_next_schedulable_pending(self) -> dict[str, Any] | None:
        if not self._pending_runs:
            return None
        rounds = len(self._pending_runs)
        for _ in range(rounds):
            pending = self._pending_runs.popleft()
            project_id = str(pending.get("project_id") or "")
            if project_id and self._project_running_count(project_id) >= self._project_max_concurrent_runs:
                self._pending_runs.append(pending)
                continue
            return pending
        return None

    def _on_run_finished(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)
        self._running_run_ids.discard(run_id)
        asyncio.create_task(self._schedule_runs())

    def _refresh_queue_positions(self) -> None:
        for index, item in enumerate(self._pending_runs, start=1):
            rid = str(item.get("run_id"))
            self._patch_run(
                rid,
                {
                    "queuePosition": index,
                    "updatedAt": utc_now(),
                },
            )

    def stop_run(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        run = self._store.get("performance_runs", run_id)
        if not run:
            return False
        if run.get("status") in {"completed", "failed", "cancelled"}:
            return False
        removed_from_queue = False
        if not task or task.done():
            next_queue = deque()
            for item in self._pending_runs:
                if str(item.get("run_id")) == run_id:
                    removed_from_queue = True
                    continue
                next_queue.append(item)
            self._pending_runs = next_queue
        if task and not task.done():
            task.cancel()
        self._running_run_ids.discard(run_id)
        self._patch_run(
            run_id,
            {
                "status": "cancelled",
                "finishedAt": utc_now(),
                "updatedAt": utc_now(),
                "errorMsg": "任务已取消",
                "logs": ["性能任务已取消" + ("(队列中移除)" if removed_from_queue else "")],
                "queuePosition": 0,
            },
        )
        asyncio.create_task(self._schedule_runs())
        return True

    async def _execute_run(
        self,
        *,
        run_id: str,
        request: PerformanceRunRequest,
        requests: list[ApiRequestPublic],
        env: ApiEnvironmentPublic | None,
    ) -> None:
        started_at = utc_now()
        self._patch_run(
            run_id,
            {
                "status": "running",
                "startedAt": started_at,
                "updatedAt": started_at,
                "logs": ["性能任务开始执行"],
            },
        )
        try:
            async def on_progress(progress: dict[str, Any]) -> None:
                self._patch_run(
                    run_id,
                    {"progress": progress, "updatedAt": utc_now()},
                )

            result = await self.run_load_test(
                request=request,
                requests=requests,
                env=env,
                progress_callback=on_progress,
            )
            result_dict = result.model_dump()
            report_path = self._artifacts_dir / f"{run_id}-performance-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "runId": run_id,
                        "profile": request.model_dump(),
                        "result": result_dict,
                        "generatedAt": utc_now(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            artifact_id = new_id("artifact")
            self._store.insert(
                "artifacts",
                {
                    "id": artifact_id,
                    "runId": run_id,
                    "type": "report",
                    "path": str(report_path.resolve()),
                    "label": "Performance Report",
                },
            )
            regression = self._evaluate_regression(
                run_id=run_id,
                project_id=request.projectId,
                collection_id=request.collectionId,
                current_result=result_dict,
            )
            logs = ["性能任务执行完成"]
            if regression and regression.get("alerts"):
                logs.append("回归告警: " + "；".join([str(item) for item in regression["alerts"]]))
            self._patch_run(
                run_id,
                {
                    "status": "completed",
                    "finishedAt": utc_now(),
                    "updatedAt": utc_now(),
                    "result": result_dict,
                    "regression": regression,
                    "errorMsg": result.errorMsg,
                    "artifactIds": [artifact_id],
                    "logs": logs,
                },
            )
        except asyncio.CancelledError:
            self._patch_run(
                run_id,
                {
                    "status": "cancelled",
                    "finishedAt": utc_now(),
                    "updatedAt": utc_now(),
                    "errorMsg": "任务已取消",
                    "logs": ["性能任务执行被取消"],
                },
            )
            raise
        except Exception as exc:
            self._patch_run(
                run_id,
                {
                    "status": "failed",
                    "finishedAt": utc_now(),
                    "updatedAt": utc_now(),
                    "errorMsg": str(exc),
                    "logs": [f"性能任务执行失败: {exc}"],
                },
            )

    def _project_running_count(self, project_id: str | None) -> int:
        if not project_id:
            return 0
        count = 0
        for rid in self._running_run_ids:
            row = self._store.get("performance_runs", rid)
            if not row:
                continue
            if str(row.get("projectId")) == str(project_id) and str(row.get("status")) in {
                "starting",
                "running",
            }:
                count += 1
        return count

    def _project_queued_count(self, project_id: str | None) -> int:
        if not project_id:
            return 0
        pid = str(project_id)
        return sum(1 for item in self._pending_runs if str(item.get("project_id")) == pid)

    def _find_baseline_run(
        self,
        *,
        project_id: str,
        collection_id: str,
        exclude_run_id: str,
    ) -> dict[str, Any] | None:
        rows = self.list_runs(project_id=project_id, limit=200)
        for item in rows:
            if str(item.get("id")) == exclude_run_id:
                continue
            if str(item.get("collectionId")) != str(collection_id):
                continue
            if str(item.get("status")) != "completed":
                continue
            if not isinstance(item.get("result"), dict):
                continue
            return item
        return None

    def _evaluate_regression(
        self,
        *,
        run_id: str,
        project_id: str,
        collection_id: str,
        current_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        baseline = self._find_baseline_run(
            project_id=project_id,
            collection_id=collection_id,
            exclude_run_id=run_id,
        )
        if not baseline:
            return None
        baseline_result = baseline.get("result") or {}
        current_tps = float(current_result.get("tps", 0) or 0)
        current_p95 = float(current_result.get("p95LatencyMs", 0) or 0)
        current_err = float(current_result.get("failCount", 0) or 0) / max(
            int(current_result.get("totalRequests", 0) or 0), 1
        )
        baseline_tps = float(baseline_result.get("tps", 0) or 0)
        baseline_p95 = float(baseline_result.get("p95LatencyMs", 0) or 0)
        baseline_err = float(baseline_result.get("failCount", 0) or 0) / max(
            int(baseline_result.get("totalRequests", 0) or 0), 1
        )
        tps_delta = round(current_tps - baseline_tps, 2)
        p95_delta = round(current_p95 - baseline_p95, 2)
        err_delta = round(current_err - baseline_err, 6)
        alerts: list[str] = []
        if p95_delta > self._regression_max_p95_delta_ms:
            alerts.append(
                f"P95 延迟回归 +{p95_delta:.2f}ms (阈值 +{self._regression_max_p95_delta_ms:.2f}ms)"
            )
        if err_delta > self._regression_max_error_rate_delta:
            alerts.append(
                "错误率回归 "
                f"+{err_delta*100:.2f}% (阈值 +{self._regression_max_error_rate_delta*100:.2f}%)"
            )
        if tps_delta < self._regression_min_tps_delta:
            alerts.append(
                f"吞吐回归 {tps_delta:.2f} (阈值 {self._regression_min_tps_delta:.2f})"
            )
        return {
            "hasBaseline": True,
            "baselineRunId": baseline.get("id"),
            "baselineCreatedAt": baseline.get("createdAt"),
            "deltas": {
                "tpsDelta": tps_delta,
                "p95DeltaMs": p95_delta,
                "errorRateDelta": err_delta,
            },
            "thresholds": {
                "maxP95DeltaMs": self._regression_max_p95_delta_ms,
                "maxErrorRateDelta": self._regression_max_error_rate_delta,
                "minTpsDelta": self._regression_min_tps_delta,
            },
            "regressed": len(alerts) > 0,
            "alerts": alerts,
        }

    def _export_run_csv(self, run: dict[str, Any]) -> bytes:
        result = run.get("result") if isinstance(run.get("result"), dict) else {}
        progress = run.get("progress") if isinstance(run.get("progress"), dict) else {}
        time_series = (
            result.get("timeSeries")
            if isinstance(result, dict) and isinstance(result.get("timeSeries"), list)
            else []
        )
        regression = run.get("regression") if isinstance(run.get("regression"), dict) else None
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "runId",
                "projectId",
                "collectionId",
                "status",
                "createdAt",
                "startedAt",
                "finishedAt",
                "progressTotalRequests",
                "progressSuccessCount",
                "progressFailCount",
                "resultTotalRequests",
                "resultSuccessCount",
                "resultFailCount",
                "avgLatencyMs",
                "p95LatencyMs",
                "p99LatencyMs",
                "maxLatencyMs",
                "tps",
                "passedSla",
                "errorMsg",
            ]
        )
        writer.writerow(
            [
                run.get("id"),
                run.get("projectId"),
                run.get("collectionId"),
                run.get("status"),
                run.get("createdAt"),
                run.get("startedAt"),
                run.get("finishedAt"),
                progress.get("totalRequests"),
                progress.get("successCount"),
                progress.get("failCount"),
                result.get("totalRequests"),
                result.get("successCount"),
                result.get("failCount"),
                result.get("avgLatencyMs"),
                result.get("p95LatencyMs"),
                result.get("p99LatencyMs"),
                result.get("maxLatencyMs"),
                result.get("tps"),
                result.get("passedSla"),
                result.get("errorMsg"),
            ]
        )
        if regression:
            writer.writerow([])
            writer.writerow(["Regression Summary"])
            writer.writerow(
                [
                    "regressed",
                    "baselineRunId",
                    "tpsDelta",
                    "p95DeltaMs",
                    "errorRateDelta",
                ]
            )
            deltas = regression.get("deltas") if isinstance(regression.get("deltas"), dict) else {}
            writer.writerow(
                [
                    regression.get("regressed"),
                    regression.get("baselineRunId"),
                    deltas.get("tpsDelta"),
                    deltas.get("p95DeltaMs"),
                    deltas.get("errorRateDelta"),
                ]
            )
            alerts = regression.get("alerts")
            if isinstance(alerts, list):
                writer.writerow([])
                writer.writerow(["Regression Alerts"])
                writer.writerow(["index", "alert"])
                for idx, alert in enumerate(alerts, start=1):
                    writer.writerow([idx, str(alert)])
        writer.writerow([])
        writer.writerow(["Time Series"])
        writer.writerow(["timestamp", "tps", "latencyMs", "errorRate"])
        for point in time_series:
            if not isinstance(point, dict):
                continue
            writer.writerow(
                [
                    point.get("timestamp"),
                    point.get("tps"),
                    point.get("latencyMs"),
                    point.get("errorRate"),
                ]
            )
        return ("\ufeff" + output.getvalue()).encode("utf-8")

    def _patch_run(self, run_id: str, patch: dict[str, Any]) -> None:
        current = self._store.get("performance_runs", run_id)
        if not current:
            return
        merged = dict(current)
        for key, value in patch.items():
            if key == "logs" and isinstance(value, list):
                merged["logs"] = [
                    *(
                        [str(item) for item in merged.get("logs", [])]
                        if isinstance(merged.get("logs"), list)
                        else []
                    ),
                    *[str(item) for item in value],
                ]
            else:
                merged[key] = value
        self._store.update("performance_runs", run_id, merged)

    @staticmethod
    def _load_csv_variables(data_file_uri: str | None) -> list[dict[str, str]]:
        if not data_file_uri:
            return []
        raw = str(data_file_uri).strip()
        if not raw:
            return []
        if raw.startswith("file://"):
            raw = raw[7:]
        path = Path(raw)
        if not path.is_file():
            raise ValueError(f"数据文件不存在: {data_file_uri}")
        rows: list[dict[str, str]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row:
                    continue
                normalized = {
                    str(k).strip(): str(v).strip()
                    for k, v in row.items()
                    if str(k).strip()
                }
                if normalized:
                    rows.append(normalized)
        if not rows:
            raise ValueError("CSV 数据文件为空或缺少有效表头")
        return rows

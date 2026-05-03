from __future__ import annotations

import logging
from typing import Any, List, Optional
from datetime import datetime, timedelta, timezone
from collections import Counter
import csv
import io
import json

from app.models import TestRun, TestCase
from app.repositories.run_repo import TestRunRepository
from app.repositories.case_repo import TestCaseRepository
from app.store import JsonStore

logger = logging.getLogger(__name__)

class ReportingService:
    def __init__(self, run_repo: TestRunRepository, case_repo: TestCaseRepository, store: JsonStore):
        self._run_repo = run_repo
        self._case_repo = case_repo
        self._store = store

    def get_dashboard_stats(self, project_id: Optional[str] = None) -> dict[str, Any]:
        """
        Get overall dashboard statistics, optionally filtered by project.
        """
        runs_raw = self._run_repo.list_by_project(project_id, limit=100)
        
        total_runs = len(runs_raw)
        passed = sum(1 for r in runs_raw if r.get("status") == "passed")
        failed = sum(1 for r in runs_raw if r.get("status") == "failed")
        pass_rate = round((passed / total_runs * 100), 1) if total_runs > 0 else 0
        
        project_count = 0
        case_count = 0
        
        if project_id:
            project_count = 1
            case_res = self._case_repo.search(project_id=project_id, page_size=1)
            case_count = case_res["total"]
        else:
            case_res = self._case_repo.search(page_size=1)
            case_count = case_res["total"]
            
            db = self._case_repo._db
            proj_row = db.fetchone("SELECT COUNT(*) as c FROM projects WHERE deleted_at IS NULL")
            project_count = proj_row["c"] if proj_row else 0

        recent_runs = runs_raw[:5]
        
        return {
            "totalRuns": total_runs,
            "passedRuns": passed,
            "failedRuns": failed,
            "passRate": pass_rate,
            "totalCases": case_count,
            "totalProjects": project_count,
            "recentRuns": recent_runs,
            "moduleCoverage": []
        }

    def list_run_reports(
        self,
        *,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        runner_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        source_rows = self._run_repo.list_by_project(project_id, limit=None)
        status_value = str(status or "").strip().lower()
        runner_value = str(runner_type or "").strip().lower()

        filtered: list[dict[str, Any]] = []
        for row in source_rows:
            if status_value and str(row.get("status") or "").strip().lower() != status_value:
                continue
            if runner_value and str(row.get("runnerType") or "").strip().lower() != runner_value:
                continue
            filtered.append(row)

        page_value = max(int(page or 1), 1)
        page_size_value = max(min(int(page_size or 20), 200), 1)
        total = len(filtered)
        offset = (page_value - 1) * page_size_value
        page_items = filtered[offset : offset + page_size_value]

        items: list[dict[str, Any]] = []
        for row in page_items:
            case_title = str(row.get("caseId") or "")
            case_row = self._case_repo.get_by_id(case_title, include_deleted=True) if case_title else None
            if case_row and case_row.get("title"):
                case_title = str(case_row.get("title"))
            artifacts = self._run_repo.list_artifacts_by_run(str(row.get("id") or ""))
            items.append(
                {
                    "id": row.get("id"),
                    "projectId": row.get("projectId"),
                    "caseId": row.get("caseId"),
                    "caseTitle": case_title,
                    "runnerType": row.get("runnerType"),
                    "status": row.get("status"),
                    "summary": row.get("summary") or "",
                    "artifactCount": len(artifacts),
                    "createdAt": row.get("createdAt"),
                    "updatedAt": row.get("updatedAt"),
                    "startedAt": row.get("startedAt"),
                    "finishedAt": row.get("finishedAt"),
                }
            )

        return {
            "items": items,
            "total": total,
            "page": page_value,
            "pageSize": page_size_value,
            "hasNext": offset + len(items) < total,
        }

    def delete_run_report(self, run_id: str) -> bool:
        return self._run_repo.delete_by_id(run_id)

    def restore_run_report(self, run_id: str) -> bool:
        return self._run_repo.restore_by_id(run_id)

    def batch_delete_run_reports(self, run_ids: list[str]) -> int:
        deleted = 0
        for run_id in run_ids:
            if self._run_repo.delete_by_id(run_id):
                deleted += 1
        return deleted

    def get_execution_summary(
        self,
        *,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        runner_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 10,
        limit: int = 500,
    ) -> dict[str, Any]:
        rows = self._run_repo.list_by_project(project_id, limit=max(1, min(int(limit), 2000)))
        filtered_rows = self._filter_runs(
            rows,
            status=status,
            runner_type=runner_type,
            start_date=start_date,
            end_date=end_date,
        )
        total_runs = len(filtered_rows)
        passed = sum(1 for item in filtered_rows if str(item.get("status")) == "passed")
        failed = sum(1 for item in filtered_rows if str(item.get("status")) == "failed")
        running = sum(1 for item in filtered_rows if str(item.get("status")) == "running")
        queued = total_runs - passed - failed - running
        pass_rate = round((passed / total_runs * 100), 1) if total_runs else 0.0

        status_breakdown = {
            "passed": passed,
            "failed": failed,
            "running": running,
            "queued": max(queued, 0),
        }
        runner_breakdown = dict(Counter(str(item.get("runnerType") or "unknown").lower() for item in filtered_rows))
        trends = self._build_trends(filtered_rows, days=days)
        top_failed_cases = self._build_top_failed_cases(filtered_rows, limit=5)
        top_failure_reasons = self._build_top_failure_reasons(filtered_rows, limit=5)

        return {
            "totalRuns": total_runs,
            "passRate": pass_rate,
            "statusBreakdown": status_breakdown,
            "runnerBreakdown": runner_breakdown,
            "topFailedCases": top_failed_cases,
            "topFailureReasons": top_failure_reasons,
            "trends": trends,
        }

    def export_execution_summary(
        self,
        *,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        runner_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 10,
        limit: int = 500,
        format_name: str = "json",
        template: str = "weekly",
    ) -> tuple[bytes, str, str]:
        summary = self.get_execution_summary(
            project_id=project_id,
            status=status,
            runner_type=runner_type,
            start_date=start_date,
            end_date=end_date,
            days=days,
            limit=limit,
        )
        fmt = str(format_name or "json").lower()
        if fmt == "json":
            return (
                json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8"),
                "application/json; charset=utf-8",
                "execution-summary.json",
            )
        if fmt == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["section", "key", "value"])
            writer.writerow(["summary", "totalRuns", summary.get("totalRuns", 0)])
            writer.writerow(["summary", "passRate", summary.get("passRate", 0)])
            for status_key, count in (summary.get("statusBreakdown") or {}).items():
                writer.writerow(["statusBreakdown", status_key, count])
            for runner_key, count in (summary.get("runnerBreakdown") or {}).items():
                writer.writerow(["runnerBreakdown", runner_key, count])
            for idx, item in enumerate(summary.get("topFailedCases") or [], start=1):
                writer.writerow(
                    [
                        "topFailedCases",
                        f"{idx}:{item.get('caseTitle') or item.get('caseId')}",
                        item.get("failedCount", 0),
                    ]
                )
            for item in summary.get("trends") or []:
                writer.writerow(["trends", str(item.get("day")), json.dumps(item, ensure_ascii=False)])
            csv_text = output.getvalue()
            return ("\ufeff" + csv_text).encode("utf-8"), "text/csv; charset=utf-8", "execution-summary.csv"
        if fmt == "markdown":
            period_text = self._report_period_text(template, days)
            lines: list[str] = []
            lines.append(f"# 自动化测试{('周报' if str(template).lower() == 'weekly' else '月报')}")
            lines.append("")
            lines.append(f"- 统计周期: {period_text}")
            lines.append(f"- 总执行: {summary.get('totalRuns', 0)}")
            lines.append(f"- 通过率: {summary.get('passRate', 0)}%")
            lines.append("")
            status_breakdown = summary.get("statusBreakdown") or {}
            lines.append("## 执行状态分布")
            lines.append(
                f"- passed: {status_breakdown.get('passed', 0)} | failed: {status_breakdown.get('failed', 0)} | running: {status_breakdown.get('running', 0)} | queued: {status_breakdown.get('queued', 0)}"
            )
            lines.append("")
            lines.append("## Runner 分布")
            runner_breakdown = summary.get("runnerBreakdown") or {}
            for key, value in runner_breakdown.items():
                lines.append(f"- {key}: {value}")
            lines.append("")
            lines.append("## 失败用例 Top")
            for item in (summary.get("topFailedCases") or []):
                lines.append(f"- {item.get('caseTitle') or item.get('caseId')}: {item.get('failedCount', 0)} 次")
            if not (summary.get("topFailedCases") or []):
                lines.append("- 暂无失败用例")
            lines.append("")
            lines.append("## 失败原因聚类 Top")
            for item in (summary.get("topFailureReasons") or []):
                lines.append(f"- {item.get('reason')}: {item.get('count', 0)} 次")
            if not (summary.get("topFailureReasons") or []):
                lines.append("- 暂无失败原因")
            lines.append("")
            lines.append("## 趋势")
            for item in (summary.get("trends") or []):
                lines.append(
                    f"- {item.get('day')}: P{item.get('passed', 0)} F{item.get('failed', 0)} R{item.get('running', 0)} Q{item.get('queued', 0)}"
                )
            return (
                "\n".join(lines).encode("utf-8"),
                "text/markdown; charset=utf-8",
                f"execution-{str(template).lower()}-report.md",
            )
        raise ValueError(f"Unsupported export format: {format_name}")

    def get_run_report(self, run_id: str) -> Optional[dict[str, Any]]:
        """
        Assemble a comprehensive report for a specific run.
        Includes case details and artifacts.
        """
        run_data = self._run_repo.get_by_id(run_id)
        if not run_data:
            return None

        try:
            run = TestRun.model_validate(run_data)
            run_dump = run.model_dump()
            case_id = str(run.caseId)
        except Exception as exc:
            logger.warning("reporting.get_run_report: invalid run data for %s: %s", run_id, exc)
            runner_type_raw = str(run_data.get("runnerType") or run_data.get("runner_type") or "api").lower()
            if runner_type_raw not in {"api", "ui"}:
                runner_type_raw = "api"
            status_raw = str(run_data.get("status") or "queued").lower()
            if status_raw not in {"queued", "running", "passed", "failed"}:
                status_raw = "failed"
            run_dump = {
                "id": str(run_data.get("id") or run_id),
                "projectId": str(run_data.get("projectId") or run_data.get("project_id") or ""),
                "caseId": str(run_data.get("caseId") or run_data.get("case_id") or ""),
                "runnerType": runner_type_raw,
                "status": status_raw,
                "startedAt": run_data.get("startedAt") or run_data.get("started_at"),
                "finishedAt": run_data.get("finishedAt") or run_data.get("finished_at"),
                "summary": str(run_data.get("summary") or "运行数据存在字段异常，已降级展示。"),
                "logs": run_data.get("logs") if isinstance(run_data.get("logs"), list) else [],
                "artifactIds": run_data.get("artifactIds") if isinstance(run_data.get("artifactIds"), list) else [],
                "sequential": bool(run_data.get("sequential") or False),
                "createdAt": str(run_data.get("createdAt") or run_data.get("created_at") or ""),
                "updatedAt": str(run_data.get("updatedAt") or run_data.get("updated_at") or ""),
            }
            case_id = str(run_dump.get("caseId") or "")

        case_data = None
        if case_id:
            try:
                case_data = self._case_repo.get_by_id(case_id, include_deleted=True)
            except Exception as exc:
                logger.warning("reporting.get_run_report: failed to load case %s: %s", case_id, exc)
                case_data = None

        try:
            artifacts_raw = self._store.list_by_json_field(
                "artifacts",
                field_name="runId",
                field_value=run_id
            )
        except Exception as exc:
            logger.warning("reporting.get_run_report: failed to load artifacts for %s: %s", run_id, exc)
            artifacts_raw = []

        return {
            "run": run_dump,
            "case": dict(case_data) if case_data else None,
            "artifacts": artifacts_raw
        }

    @staticmethod
    def _parse_datetime(raw: Any) -> datetime | None:
        if not isinstance(raw, str) or not raw.strip():
            return None
        text = raw.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except Exception:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _build_trends(self, rows: list[dict[str, Any]], *, days: int = 10) -> list[dict[str, Any]]:
        days = max(1, min(int(days), 30))
        now = datetime.now(timezone.utc)
        day_keys: list[str] = []
        buckets: dict[str, dict[str, Any]] = {}
        for index in range(days - 1, -1, -1):
            day = (now - timedelta(days=index)).date().isoformat()
            day_keys.append(day)
            buckets[day] = {"day": day[5:], "passed": 0, "failed": 0, "running": 0, "queued": 0}
        for row in rows:
            dt = self._parse_datetime(row.get("createdAt") or row.get("finishedAt") or row.get("startedAt"))
            if not dt:
                continue
            key = dt.date().isoformat()
            if key not in buckets:
                continue
            status_text = str(row.get("status") or "queued").lower()
            if status_text == "passed":
                buckets[key]["passed"] += 1
            elif status_text == "failed":
                buckets[key]["failed"] += 1
            elif status_text == "running":
                buckets[key]["running"] += 1
            else:
                buckets[key]["queued"] += 1
        return [buckets[key] for key in day_keys]

    def _build_top_failed_cases(self, rows: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
        failed_rows = [item for item in rows if str(item.get("status") or "").lower() == "failed"]
        failed_counter = Counter(str(item.get("caseId") or "") for item in failed_rows if str(item.get("caseId") or ""))
        result: list[dict[str, Any]] = []
        for case_id, count in failed_counter.most_common(max(1, min(int(limit), 20))):
            case_title = case_id
            try:
                case_row = self._case_repo.get_by_id(case_id, include_deleted=True)
                if case_row and case_row.get("title"):
                    case_title = str(case_row.get("title"))
            except Exception:
                case_title = case_id
            result.append({"caseId": case_id, "caseTitle": case_title, "failedCount": int(count)})
        return result

    def _build_top_failure_reasons(self, rows: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
        failed_rows = [item for item in rows if str(item.get("status") or "").lower() == "failed"]
        counter: Counter[str] = Counter()
        for row in failed_rows:
            reason = str(row.get("summary") or "").strip()
            if not reason:
                logs = row.get("logs")
                if isinstance(logs, list) and logs:
                    reason = str(logs[-1] or "").strip()
            if not reason:
                reason = "未知失败原因"
            reason = reason.split("\n")[0][:80]
            counter[reason] += 1
        return [{"reason": key, "count": int(value)} for key, value in counter.most_common(max(1, min(int(limit), 20)))]

    def _filter_runs(
        self,
        rows: list[dict[str, Any]],
        *,
        status: Optional[str] = None,
        runner_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        status_value = str(status or "").strip().lower()
        runner_value = str(runner_type or "").strip().lower()
        start_dt = self._parse_datetime(start_date) if start_date else None
        end_dt = self._parse_datetime(end_date) if end_date else None
        results: list[dict[str, Any]] = []
        for row in rows:
            if status_value and str(row.get("status") or "").lower() != status_value:
                continue
            if runner_value and str(row.get("runnerType") or "").lower() != runner_value:
                continue
            if start_dt or end_dt:
                run_dt = self._parse_datetime(row.get("createdAt") or row.get("finishedAt") or row.get("startedAt"))
                if not run_dt:
                    continue
                if start_dt and run_dt < start_dt:
                    continue
                if end_dt and run_dt > end_dt:
                    continue
            results.append(row)
        return results

    @staticmethod
    def _report_period_text(template: str, days: int) -> str:
        now = datetime.now(timezone.utc).date()
        tpl = str(template or "weekly").lower()
        if tpl == "monthly":
            start = (now - timedelta(days=max(30, days) - 1)).isoformat()
        else:
            start = (now - timedelta(days=max(7, min(days, 30)) - 1)).isoformat()
        return f"{start} ~ {now.isoformat()} (UTC)"

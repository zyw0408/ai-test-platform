from typing import Any, List, Optional
from app.store import JsonStore
from app.core.utils import new_id, utc_now

class TestRunRepository:
    def __init__(self, store: JsonStore):
        self._store = store

    def list_by_project(self, project_id: str | None = None, limit: int = 40) -> List[dict[str, Any]]:
        if project_id:
            return self._store.list_by_json_field("runs", field_name="projectId", field_value=project_id, sort_by="created_at", sort_order="desc", limit=limit)
        return self._store.list_all("runs", sort_by="created_at", sort_order="desc", limit=limit)

    def get_by_id(self, run_id: str) -> Optional[dict[str, Any]]:
        return self._store.get("runs", run_id)

    def update(self, run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        return self._store.update("runs", run_id, patch)

    def insert(self, run: dict[str, Any]) -> dict[str, Any]:
        return self._store.insert("runs", run)

    def delete_by_id(self, run_id: str) -> bool:
        return self._store.soft_delete("runs", run_id)

    def restore_by_id(self, run_id: str) -> bool:
        return self._store.restore("runs", run_id)

    def list_artifacts_by_run(self, run_id: str) -> List[dict[str, Any]]:
        return self._store.filter_by("artifacts", "runId", run_id)

    def create_run(
        self,
        case_id: str,
        project_id: str,
        runner_type: str,
        triggered_by: str,
        sequential: bool = False,
    ) -> dict[str, Any]:
        now = utc_now()
        run = {
            "id": new_id("run"),
            "caseId": case_id,
            "projectId": project_id,
            "runnerType": runner_type,
            "status": "queued",
            "startedAt": None,
            "finishedAt": None,
            "summary": "任务已创建，等待执行",
            "logs": [f"任务由用户 {triggered_by} 创建"],
            "artifactIds": [],
            "triggeredBy": triggered_by,
            "sequential": sequential,
            "createdAt": now,
            "updatedAt": now,
        }
        return self._store.insert("runs", run)

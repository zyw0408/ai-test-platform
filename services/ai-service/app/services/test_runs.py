from typing import Any, List, Optional
from app.repositories.run_repo import TestRunRepository
from app.core.utils import new_id, utc_now

class TestRunService:
    def __init__(self, repo: TestRunRepository):
        self._repo = repo

    def list_runs(self, project_id: str | None = None, limit: int = 40) -> List[dict[str, Any]]:
        return self._repo.list_by_project(project_id=project_id, limit=limit)

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        return self._repo.get_by_id(run_id)

    def update_run(self, run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        return self._repo.update(run_id, patch)

    def create_run(self, run_data: dict[str, Any]) -> dict[str, Any]:
        return self._repo.insert(run_data)

    def delete_run(self, run_id: str) -> bool:
        return self._repo.delete_by_id(run_id)

    def batch_delete_runs(self, run_ids: list[str]) -> dict[str, Any]:
        deleted = 0
        failed_ids: list[str] = []
        for run_id in run_ids:
            if self._repo.delete_by_id(run_id):
                deleted += 1
            else:
                failed_ids.append(run_id)
        return {
            "deleted": deleted,
            "failedIds": failed_ids,
        }

    def create_run_with_params(
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
        return self._repo.insert(run)

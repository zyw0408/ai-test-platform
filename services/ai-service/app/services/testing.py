from typing import Any, List, Optional
from app.repositories.case_repo import TestCaseRepository
from app.models import TestCaseCreateRequest, TestCaseUpdateRequest

class TestCaseService:
    def __init__(self, repo: TestCaseRepository):
        self._repo = repo

    def list_cases(
        self,
        *,
        project_id: Optional[str] = None,
        kind: Optional[str] = None,
        q: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        return self._repo.search(
            project_id=project_id,
            kind=kind,
            q=q,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order
        )

    def create_case(
        self,
        *,
        project_id: str,
        title: str,
        content: str | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        # Compatibility with legacy routers
        data = {
            "projectId": project_id,
            "title": title,
            "objective": content,
            "createdBy": created_by,
        }
        return self._repo.create(data)

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        return self._repo.get_by_id(case_id)

    def update_case(self, case_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        if self._repo.update(case_id, updates):
            return self._repo.get_by_id(case_id)
        return None

    def delete_case(self, case_id: str) -> bool:
        return self._repo.delete_soft(case_id)

    def batch_delete(self, case_ids: List[str]) -> int:
        return self._repo.batch_delete_soft(case_ids)

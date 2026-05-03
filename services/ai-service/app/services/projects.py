from __future__ import annotations

from typing import Any, List, Optional
from app.repositories.project_repo import ProjectRepository

class ProjectService:
    def __init__(self, repo: ProjectRepository) -> None:
        self._repo = repo

    def list_projects(self, org_ids: List[str]) -> List[dict[str, Any]]:
        return self._repo.list_by_orgs(org_ids)

    def search_projects(
        self,
        *,
        org_ids: List[str],
        query_text: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        offset = (page - 1) * page_size
        return self._repo.search(
            org_ids=org_ids,
            query_text=query_text,
            limit=page_size,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order
        )

    def get_project_by_id(self, project_id: str) -> Optional[dict[str, Any]]:
        return self._repo.get_by_id(project_id)

    def create_project(self, *, org_id: str, name: str, description: str = "") -> dict[str, Any]:
        if self._repo.exists_by_name(org_id, name.strip()):
            raise ValueError(f"项目名称「{name.strip()}」已存在，请使用其他名称")
        return self._repo.create(org_id, name.strip(), description.strip())

    def update_project(self, project_id: str, *, name: Optional[str] = None, description: Optional[str] = None) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if name is not None:
            data["name"] = name.strip()
        if description is not None:
            data["description"] = description.strip()
            
        if not data:
            return self.get_project_by_id(project_id) or {}
            
        self._repo.update(project_id, data)
        return self.get_project_by_id(project_id) or {}

    def delete_project(self, project_id: str) -> None:
        self._repo.delete(project_id)

    def list_deleted_projects(
        self,
        *,
        org_ids: List[str],
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        offset = (page - 1) * page_size
        return self._repo.list_deleted(
            org_ids=org_ids,
            limit=page_size,
            offset=offset
        )

    def restore_project(self, project_id: str) -> Optional[dict[str, Any]]:
        return self._repo.restore(project_id)

    def purge_deleted_project(self, project_id: str) -> bool:
        return self._repo.purge_deleted(project_id)

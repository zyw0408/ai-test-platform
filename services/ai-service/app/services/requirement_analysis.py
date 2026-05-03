from __future__ import annotations

import csv
import io
import json
import re
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.cache import CacheClient
from app.config import Settings
from app.database import Database
from app.models import new_id, utc_now
from app.services.providers import ModelProvider, build_provider
from app.repositories.requirement_repo import RequirementRepository
from app.repositories.ai_operation_repo import AiOperationRepository
from app.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)

_REQUIREMENT_STATUSES = {"draft", "analyzing", "analyzed", "failed"}

class RequirementAnalysisService:
    def __init__(
        self,
        *,
        db: Database,
        cache: CacheClient,
        provider: ModelProvider,
        settings: Settings,
        requirement_repo: RequirementRepository,
        ai_op_repo: AiOperationRepository,
        user_repo: UserRepository,
    ) -> None:
        self._db = db
        self._cache = cache
        self._provider = provider
        self._settings = settings
        self._repo = requirement_repo
        self._ai_repo = ai_op_repo
        self._user_repo = user_repo
        self._cache_ttl_seconds = max(settings.cache_default_ttl_seconds, 30)

    # --- CRUD Operations (using Repository) ---

    def create_requirement(
        self,
        *,
        org_id: str,
        project_id: str,
        title: str,
        content: str,
        source_spec_id: str | None,
        tags: list[str],
        created_by: str | None,
    ) -> dict[str, Any]:
        normalized_project_id = project_id.strip()
        normalized_title = title.strip()
        normalized_content = content.strip()
        if not normalized_project_id:
            raise ValueError("project_id 不能为空")
        if not normalized_title:
            raise ValueError("title 不能为空")
        if not normalized_content:
            raise ValueError("content 不能为空")

        if self._repo.exists_same(normalized_project_id, normalized_title, normalized_content):
            raise ValueError(f"需求「{normalized_title}」已存在，请勿重复创建")

        now = utc_now()
        requirement_id = new_id("req")
        normalized_tags = self._normalize_tags(tags)
        
        self._repo.create({
            "id": requirement_id,
            "org_id": org_id,
            "project_id": normalized_project_id,
            "source_spec_id": source_spec_id.strip() if isinstance(source_spec_id, str) and source_spec_id.strip() else None,
            "title": normalized_title,
            "content": normalized_content,
            "tags_json": json.dumps(normalized_tags, ensure_ascii=False),
            "status": "draft",
            "latest_analysis_version": None,
            "created_by": created_by,
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
        })
        
        self._invalidate_requirement(requirement_id)
        requirement = self.get_requirement(requirement_id)
        if not requirement:
            raise ValueError("创建需求失败")
        return requirement

    def list_requirements(
        self,
        *,
        org_ids: list[str] | None = None,
        project_id: str | None = None,
        q: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        include_deleted: bool = False,
        only_deleted: bool = False,
    ) -> dict[str, Any]:
        cache_key = self._requirements_list_key(
            project_id or (org_ids[0] if org_ids else "all"),
            q,
            status,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            include_deleted=include_deleted,
            only_deleted=only_deleted,
        )
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        items, total = self._repo.search(
            org_ids=org_ids,
            project_id=project_id,
            q=q,
            status=status,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            include_deleted=include_deleted,
            only_deleted=only_deleted,
        )

        final_results = {
            "total": total,
            "items": [self._row_to_requirement(row) for row in items],
            "page": page,
            "pageSize": page_size,
            "hasNext": (page * page_size) < total,
        }
        self._cache.set(cache_key, final_results, expire=60)
        return final_results

    def get_requirement(self, requirement_id: str) -> dict[str, Any] | None:
        cached = self._cache.get(self._requirement_detail_key(requirement_id))
        if cached:
            return cached

        row = self._repo.get_by_id(requirement_id)
        if not row:
            return None

        requirement = self._row_to_requirement(row)
        self._cache.set(self._requirement_detail_key(requirement_id), requirement, expire=300)
        return requirement

    def update_requirement(self, requirement_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        repo_updates = {}
        if "title" in updates: 
            repo_updates["title"] = updates["title"].strip()
        if "content" in updates: 
            repo_updates["content"] = updates["content"].strip()
        if "status" in updates: 
            repo_updates["status"] = updates["status"]
        if "tags" in updates: 
            repo_updates["tags_json"] = json.dumps(self._normalize_tags(updates["tags"]), ensure_ascii=False)
        
        if not repo_updates:
            return self.get_requirement(requirement_id) or {}

        repo_updates["updated_at"] = utc_now()
        self._repo.update(requirement_id, repo_updates)
        self._invalidate_requirement(requirement_id)
        
        return self.get_requirement(requirement_id) or {}

    def delete_requirement(self, requirement_id: str, *, hard: bool = False) -> bool:
        if hard:
            success = self._repo.hard_delete(requirement_id)
        else:
            success = self._repo.soft_delete(requirement_id)
        
        if success:
            self._invalidate_requirement(requirement_id)
        return success

    def batch_delete_requirements(self, requirement_ids: list[str], *, hard: bool = False) -> int:
        count = self._repo.batch_delete(requirement_ids, hard=hard)
        if count > 0:
            for rid in requirement_ids:
                self._invalidate_requirement(rid)
        return count

    def batch_restore_requirements(self, requirement_ids: list[str]) -> int:
        count = self._repo.batch_restore(requirement_ids)
        if count > 0:
            for rid in requirement_ids:
                self._invalidate_requirement(rid)
        return count

    def batch_update_status(self, requirement_ids: list[str], status: str) -> int:
        if status not in _REQUIREMENT_STATUSES:
            raise ValueError(f"无效的状态: {status}")
        
        count = self._repo.batch_update_status(requirement_ids, status)
        if count > 0:
            for rid in requirement_ids:
                self._invalidate_requirement(rid)
        return count

    def list_deleted_requirements(
        self,
        *,
        org_ids: list[str] | None = None,
        project_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        return self.list_requirements(
            org_ids=org_ids,
            project_id=project_id,
            page=page,
            page_size=page_size,
            only_deleted=True,
        )

    def restore_requirement(self, requirement_id: str) -> dict[str, Any] | None:
        success = self._repo.restore(requirement_id)
        if not success:
            return None
        self._invalidate_requirement(requirement_id)
        return self.get_requirement(requirement_id)

    # --- Import Operations ---

    def import_requirements(
        self,
        *,
        org_id: str,
        project_id: str,
        file_name: str,
        file_bytes: bytes,
        created_by: str | None = None,
        dedupe: bool = True,
        rollback_on_error: bool = False,
    ) -> dict[str, Any]:
        records, parse_warnings = self._parse_import_records(
            file_name=file_name,
            file_bytes=file_bytes,
        )
        if not records:
            return {"total": 0, "created": [], "warnings": parse_warnings}

        normalized_project_id = project_id.strip()
        created: list[dict[str, Any]] = []
        warnings = list(parse_warnings)
        failed_count = 0
        
        seen_fingerprints: set[str] = set()
        for index, record in enumerate(records, start=1):
            title = self._as_text(record.get("title")) or ""
            content = self._as_text(record.get("content")) or ""
            if not title and content:
                title = self._truncate_text(content, max_length=60)
            if title and not content:
                content = title
            if not title or not content:
                warnings.append(f"第 {index} 条记录缺少标题或正文，已跳过")
                failed_count += 1
                continue

            tags = self._as_list(record.get("tags"))
            desired_status = self._as_text(record.get("status"))
            fingerprint = f"{title.lower()}::{content.lower()}"
            if dedupe and fingerprint in seen_fingerprints:
                warnings.append(f"第 {index} 条记录与本次导入其他记录重复，已跳过")
                continue
            seen_fingerprints.add(fingerprint)
            
            if dedupe and self._exists_same_requirement(
                project_id=normalized_project_id,
                title=title,
                content=content,
            ):
                warnings.append(f"第 {index} 条记录与现有需求重复，已跳过")
                continue
                
            try:
                item = self.create_requirement(
                    org_id=org_id,
                    project_id=normalized_project_id,
                    title=title,
                    content=content,
                    source_spec_id=None,
                    tags=tags,
                    created_by=created_by,
                )
                if desired_status:
                    normalized_status = desired_status.lower()
                    if normalized_status in _REQUIREMENT_STATUSES and normalized_status != "draft":
                        item = self.update_requirement(
                            requirement_id=item["id"],
                            updates={"status": normalized_status},
                        )
                created.append(item)
            except Exception as exc:
                warnings.append(f"第 {index} 条记录导入失败: {exc}")
                failed_count += 1

        if rollback_on_error and failed_count > 0 and created:
            for item in created:
                self._repo.hard_delete(item["id"])
            self._invalidate_requirement()
            warnings.append("导入存在失败记录，已按回滚策略撤销本次已创建数据")
            created = []

        return {
            "total": len(records),
            "created": created,
            "warnings": warnings,
        }

    def _exists_same_requirement(self, project_id: str, title: str, content: str) -> bool:
        return self._repo.exists_same(project_id, title, content)

    # --- AI Analysis Operations ---

    def get_latest_analysis(self, requirement_id: str) -> dict[str, Any] | None:
        cached = self._cache.get(self._analysis_latest_key(requirement_id))
        if cached:
            return cached

        row = self._repo.get_latest_analysis_version(requirement_id)
        if not row:
            return None

        analysis = self._row_to_analysis(row)
        self._cache.set(self._analysis_latest_key(requirement_id), analysis, expire=600)
        return analysis

    def get_ai_operation(self, operation_id: str) -> dict[str, Any]:
        cached = self._cache.get(self._operation_key(operation_id))
        if cached:
            return cached

        row = self._ai_repo.get_by_id(operation_id)
        if not row:
            raise ValueError(f"AI 操作记录 {operation_id} 不存在")

        operation = self._row_to_operation(row)
        self._cache.set(self._operation_key(operation_id), operation, expire=60)
        return operation

    def create_analysis_operation(
        self,
        *,
        requirement_id: str,
        created_by: str | None,
    ) -> dict[str, Any]:
        requirement = self.get_requirement(requirement_id)
        if not requirement:
            raise KeyError("requirement not found")

        operation_id = new_id("aop")
        now = utc_now()
        request_payload = {"requirementId": requirement_id}
        
        self._ai_repo.create({
            "id": operation_id,
            "operation_type": "requirement_analysis",
            "target_type": "requirement",
            "target_id": requirement_id,
            "status": "queued",
            "request_payload": json.dumps(request_payload, ensure_ascii=False),
            "response_payload": None,
            "error_message": None,
            "created_by": created_by,
            "attempt_count": 0,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        })
        
        self._repo.update(requirement_id, {"status": "analyzing"})
        self._invalidate_requirement(requirement_id)
        return self.get_ai_operation(operation_id)

    async def execute_operation(
        self, 
        operation_id: str, 
        *, 
        provider: ModelProvider | None = None
    ) -> dict[str, Any]:
        operation = self._ai_repo.get_by_id(operation_id)
        if not operation:
            raise KeyError("ai operation not found")
        if operation["operation_type"] != "requirement_analysis":
            raise ValueError("暂不支持的 AI 操作类型")

        requirement_id = operation["target_id"]
        if operation["status"] == "succeeded":
            return {
                "operation": self.get_ai_operation(operation_id),
                "analysis": self.get_latest_analysis(requirement_id),
            }

        requirement = self.get_requirement(requirement_id)
        if not requirement:
            self._mark_operation_failed(operation_id, "关联需求不存在")
            raise KeyError("requirement not found")

        self._mark_operation_running(operation_id)
        
        try:
            active_provider = provider or self._provider
            ai_settings = self._get_ai_settings(operation.get("created_by"))
            
            analysis_data = await self._perform_requirement_analysis_step(
                requirement=requirement,
                provider=active_provider,
                ai_settings=ai_settings,
            )
            
            analysis_id = new_id("anl")
            self._repo.create_analysis_version({
                "id": analysis_id,
                "requirement_id": requirement_id,
                "version": (requirement.get("version") or 0) + 1,
                "analysis_json": json.dumps(analysis_data, ensure_ascii=False),
                "ai_operation_id": operation_id,
                "created_at": utc_now(),
            })
            
            self._repo.update(requirement_id, {
                "status": "analyzed",
                "latest_analysis_version": (requirement.get("version") or 0) + 1,
            })
            
            self._mark_operation_succeeded(operation_id, response_payload=analysis_data)
            self._invalidate_requirement(requirement_id)
            
            return {
                "operation": self.get_ai_operation(operation_id),
                "analysis": self.get_latest_analysis(requirement_id),
            }
            
        except Exception as exc:
            logger.exception(f"AI Analysis failed for operation {operation_id}")
            self._mark_operation_failed(operation_id, str(exc))
            self._repo.update(requirement_id, {"status": "failed"})
            self._invalidate_requirement(requirement_id)
            raise

    async def _perform_requirement_analysis_step(
        self,
        *,
        requirement: dict[str, Any],
        provider: ModelProvider,
        ai_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt = (
            f"请分析以下软件需求，并提供结构化的分析结果。\n\n"
            f"标题: {requirement['title']}\n"
            f"内容: {requirement['content']}\n\n"
            f"请包含以下字段:\n"
            f"1. summary: 需求简要总结\n"
            f"2. functionalRequirements: 功能点列表\n"
            f"3. nonFunctionalRequirements: 非功能性点列表\n"
            f"4. acceptanceCriteria: 验收标准列表\n"
            f"5. risks: 潜在风险列表\n"
            f"6. testFocus: 测试关注点\n"
            f"7. assumptions: 假设条件"
        )
        
        settings = ai_settings or {}
        system_prompt = settings.get("systemPrompt") or "你是一个资深的软件测试工程师和业务分析师。"
        temperature = float(settings.get("temperature") or 0.7)
        max_tokens = int(settings.get("maxTokens") or 2000)

        response = await provider.generate_structured_response(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_model=None,
        )
        
        if isinstance(response, str):
            try:
                data = json.loads(response)
            except:
                data = {"summary": response, "source": "llm-raw"}
        else:
            data = response
            
        data["source"] = "ai-service"
        return data

    def _get_ai_settings(self, user_id: str | None) -> dict[str, Any] | None:
        if not user_id or not self._user_repo:
            return None
        row = self._user_repo.get_ai_settings(user_id)
        return self._row_to_ai_settings(row) if row else None

    # --- Operation Status Helpers ---

    def _mark_operation_running(self, operation_id: str):
        self._ai_repo.update(operation_id, {
            "status": "running",
            "started_at": utc_now(),
            "updated_at": utc_now(),
        })
        self._cache.delete(self._operation_key(operation_id))

    def _mark_operation_succeeded(self, operation_id: str, response_payload: dict[str, Any]):
        self._ai_repo.update(operation_id, {
            "status": "succeeded",
            "response_payload": json.dumps(response_payload, ensure_ascii=False),
            "finished_at": utc_now(),
            "updated_at": utc_now(),
        })
        self._cache.delete(self._operation_key(operation_id))

    def _mark_operation_failed(self, operation_id: str, error_message: str):
        self._ai_repo.update(operation_id, {
            "status": "failed",
            "error_message": error_message,
            "finished_at": utc_now(),
            "updated_at": utc_now(),
        })
        self._cache.delete(self._operation_key(operation_id))

    # --- Parsing & Validation Helpers ---

    def _parse_import_records(self, *, file_name: str, file_bytes: bytes) -> tuple[list[dict[str, Any]], list[str]]:
        extension = Path(file_name).suffix.lower()
        text = self._decode_import_text(file_bytes)

        if extension in {".txt", ".text"}:
            return self._parse_text_records(text), []
        if extension == ".md":
            return self._parse_markdown_records(text), []
        if extension == ".csv":
            return self._parse_csv_records(text)
        if extension == ".json":
            return self._parse_json_records(text)

        return self._parse_text_records(text), [f"不支持的文件类型: {extension}，已尝试作为文本解析"]

    @staticmethod
    def _decode_import_text(file_bytes: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                return file_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return file_bytes.decode("latin1", errors="ignore")

    def _parse_text_records(self, text: str) -> list[dict[str, Any]]:
        blocks = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
        records = []
        for index, block in enumerate(blocks, start=1):
            lines = [line.strip("-• \t") for line in block.splitlines() if line.strip("-• \t")]
            if not lines: continue
            title = lines[0]
            content = "\n".join(lines[1:]).strip() or lines[0]
            records.append({"title": title, "content": content})
        return records

    def _parse_markdown_records(self, text: str) -> list[dict[str, Any]]:
        heading_pattern = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
        matches = list(heading_pattern.finditer(text))
        if not matches: return self._parse_text_records(text)
        records = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            title = match.group(1).strip()
            content = text[start:end].strip()
            if title or content:
                records.append({"title": title or f"Imported {index+1}", "content": content or title})
        return records

    def _parse_csv_records(self, text: str) -> tuple[list[dict[str, Any]], list[str]]:
        stream = io.StringIO(text)
        reader = csv.DictReader(stream)
        records = []
        warnings = []
        if not reader.fieldnames:
            return [], ["CSV 缺少表头"]
            
        for row in reader:
            normalized = self._coerce_import_record(row)
            if normalized:
                records.append(normalized)
            else:
                warnings.append("部分行缺少标题或正文，已跳过")
        return records, warnings

    def _parse_json_records(self, text: str) -> tuple[list[dict[str, Any]], list[str]]:
        try:
            payload = json.loads(text)
            if isinstance(payload, list):
                items = payload
            elif isinstance(payload, dict):
                items = payload.get("requirements", payload.get("items", [payload]))
            else:
                return [], ["JSON 格式错误"]
            
            records = []
            for item in items:
                normalized = self._coerce_import_record(item)
                if normalized: records.append(normalized)
            return records, []
        except:
            return [], ["JSON 解析失败"]

    def _coerce_import_record(self, raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict): return None
        title = self._pick_value(raw, ["title", "name", "标题"])
        content = self._pick_value(raw, ["content", "description", "正文"])
        if not title and content: title = self._truncate_text(content, 60)
        if not content and title: content = title
        if not title or not content: return None
        return {"title": str(title), "content": str(content), "tags": self._coerce_tags(raw.get("tags"))}

    @staticmethod
    def _pick_value(raw: dict, keys: list[str]) -> Any:
        for k in keys:
            if k in raw: return raw[k]
        return None

    def _coerce_tags(self, value: Any) -> list[str]:
        if isinstance(value, list): return [str(v) for v in value]
        if isinstance(value, str): return [v.strip() for v in re.split(r"[,，;；]", value) if v.strip()]
        return []

    @staticmethod
    def _truncate_text(value: str, max_length: int) -> str:
        if len(value) <= max_length: return value
        return value[:max_length-3] + "..."

    @staticmethod
    def _normalize_tags(tags: list[str] | None) -> list[str]:
        if not tags: return []
        return sorted(list(set(str(t).strip() for t in tags if str(t).strip())))

    @staticmethod
    def _as_text(value: Any) -> str:
        return str(value) if value is not None else ""

    @staticmethod
    def _as_list(value: Any) -> list:
        if isinstance(value, list): return value
        if isinstance(value, str): 
            try: return json.loads(value)
            except: pass
        return []

    # --- Mappers (Row to Public/Internal Dict) ---

    def _row_to_requirement(self, row: dict[str, Any]) -> dict[str, Any]:
        tags_raw = row.get("tags_json")
        tags: list[str] = []
        if isinstance(tags_raw, str) and tags_raw:
            try:
                parsed = json.loads(tags_raw)
                if isinstance(parsed, list):
                    tags = [str(item) for item in parsed if str(item).strip()]
            except json.JSONDecodeError:
                tags = []
        latest_analysis_version = row.get("latest_analysis_version")
        return {
            "id": row["id"],
            "projectId": row["project_id"],
            "sourceSpecId": row.get("source_spec_id"),
            "title": row["title"],
            "content": row["content"],
            "status": row["status"],
            "tags": tags or [],
            "latestAnalysisVersion": int(latest_analysis_version) if latest_analysis_version is not None else None,
            "createdBy": row.get("created_by"),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _row_to_analysis(self, row: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        raw = row.get("analysis_json")
        if isinstance(raw, str) and raw:
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, dict):
                    payload = decoded
            except json.JSONDecodeError:
                payload = {}
        return {
            "id": row["id"],
            "requirementId": row["requirement_id"],
            "version": row["version"],
            "summary": self._as_text(payload.get("summary")) or "",
            "functionalRequirements": self._as_list(payload.get("functionalRequirements")),
            "nonFunctionalRequirements": self._as_list(payload.get("nonFunctionalRequirements")),
            "acceptanceCriteria": self._as_list(payload.get("acceptanceCriteria")),
            "risks": self._as_list(payload.get("risks")),
            "testFocus": self._as_list(payload.get("testFocus")),
            "assumptions": self._as_list(payload.get("assumptions")),
            "source": self._as_text(payload.get("source")) or "unknown",
            "aiOperationId": row.get("ai_operation_id"),
            "createdAt": row["created_at"],
        }

    def _row_to_operation(self, row: dict[str, Any]) -> dict[str, Any]:
        request_payload = self._parse_json_text(row.get("request_payload"))
        response_payload = self._parse_json_text(row.get("response_payload"))
        return {
            "id": row["id"],
            "operationType": row["operation_type"],
            "targetType": row["target_type"],
            "targetId": row["target_id"],
            "status": row["status"],
            "requestPayload": request_payload,
            "responsePayload": response_payload,
            "errorMessage": row.get("error_message"),
            "createdBy": row.get("created_by"),
            "attemptCount": int(row.get("attempt_count") or 0),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "startedAt": row.get("started_at"),
            "finishedAt": row.get("finished_at"),
        }

    def _row_to_ai_settings(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": row.get("ai_model", row.get("aiModel")),
            "temperature": row.get("ai_temperature", row.get("aiTemperature")),
            "maxTokens": row.get("ai_max_tokens", row.get("aiMaxTokens")),
            "systemPrompt": row.get("ai_system_prompt", row.get("aiSystemPrompt")),
        }

    @staticmethod
    def _parse_json_text(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    # --- Cache Key Helpers ---

    def _invalidate_requirement(self, requirement_id: str | None = None) -> None:
        if requirement_id:
            self._cache.delete(self._requirement_detail_key(requirement_id))
            self._cache.delete(self._analysis_latest_key(requirement_id))
        self._cache.delete_prefix("req:list:")

    @staticmethod
    def _requirements_list_key(project_token: str, q: str | None, status: str | None, **kwargs) -> str:
        q_token = quote(q or "all", safe="")
        status_token = quote(status or "all", safe="")
        params = ":".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return f"req:list:proj={project_token}:q={q_token}:st={status_token}:{params}"

    @staticmethod
    def _requirement_detail_key(requirement_id: str) -> str:
        return f"req:detail:{requirement_id}"

    @staticmethod
    def _analysis_latest_key(requirement_id: str) -> str:
        return f"req:analysis:latest:{requirement_id}"

    @staticmethod
    def _operation_key(operation_id: str) -> str:
        return f"aiop:detail:{operation_id}"

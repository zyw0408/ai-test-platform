from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
from typing import Any
from uuid import uuid4

import httpx

from app.database import Database
from app.models import new_id, utc_now, SourceSpec

try:  # pragma: no cover - optional dependency
    import yaml
except Exception:  # pragma: no cover
    yaml = None


_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_AUTH_TYPES = {"none", "bearer", "basic", "apiKey"}
_BODY_MODES = {"none", "raw", "json", "form"}
_TEMPLATE_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_.-]+)\s*}}")


class ApiTestingService:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._http_client = httpx.AsyncClient(
            follow_redirects=False,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        self._http_client_insecure = httpx.AsyncClient(
            follow_redirects=False,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            verify=False,
        )
        self._loopback_http_client = httpx.AsyncClient(
            follow_redirects=False,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )
        self._loopback_http_client_insecure = httpx.AsyncClient(
            follow_redirects=False,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
            verify=False,
        )

    async def aclose(self) -> None:
        await self._http_client.aclose()
        await self._http_client_insecure.aclose()
        await self._loopback_http_client.aclose()
        await self._loopback_http_client_insecure.aclose()

    def list_collections(self, project_id: str) -> list[dict[str, Any]]:
        rows = self._db.fetchall(
            """
            SELECT *
            FROM api_collections
            WHERE project_id = ? AND deleted_at IS NULL
            ORDER BY updated_at DESC, id ASC
            """,
            (project_id,),
        )
        return [self._row_to_collection(item) for item in rows]

    def get_collection(self, collection_id: str) -> dict[str, Any] | None:
        row = self._db.fetchone(
            """
            SELECT *
            FROM api_collections
            WHERE id = ? AND deleted_at IS NULL
            """,
            (collection_id,),
        )
        return self._row_to_collection(row) if row else None

    def create_collection(
        self,
        *,
        project_id: str,
        name: str,
        description: str,
        variables: dict[str, str],
        created_by: str | None,
    ) -> dict[str, Any]:
        normalized_project_id = project_id.strip()
        project_row = self._db.fetchone(
            "SELECT org_id FROM projects WHERE id = ? AND deleted_at IS NULL",
            (normalized_project_id,),
        )
        if not project_row:
            raise KeyError("project not found")
        org_id = str(project_row.get("org_id") or "DEFAULT_ORG")
        now = utc_now()
        collection_id = new_id("acol")
        self._db.execute(
            """
            INSERT INTO api_collections (
                id, org_id, project_id, name, description, variables_json, created_by, deleted_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                collection_id,
                org_id,
                normalized_project_id,
                name.strip(),
                description.strip(),
                json.dumps(self._normalize_variables(variables), ensure_ascii=False),
                created_by,
                None,
                now,
                now,
            ),
        )
        created = self.get_collection(collection_id)
        if not created:
            raise ValueError("创建接口集合失败")
        return created

    def get_spec(self, spec_id: str) -> SourceSpec | None:
        row = self._db.fetchone(
            "SELECT * FROM source_specs WHERE id = ?",
            (spec_id,),
        )
        if not row:
            return None
        return SourceSpec.model_validate(self._row_to_spec(row))

    def _row_to_spec(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "orgId": row.get("org_id", "DEFAULT_ORG"),
            "projectId": row["project_id"],
            "title": row.get("title") or row.get("name"),
            "kind": row.get("kind") or "swagger",
            "content": row.get("content") or "",
            "metadata": self._parse_json_dict(row.get("metadata_json"), default={}),
            "createdBy": row.get("created_by"),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def update_collection(
        self,
        *,
        collection_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        exists = self._db.fetchone(
            "SELECT id FROM api_collections WHERE id = ? AND deleted_at IS NULL",
            (collection_id,),
        )
        if not exists:
            raise KeyError("collection not found")
        fields: list[str] = []
        params: list[Any] = []
        if "name" in updates:
            name = str(updates["name"]).strip() if updates["name"] is not None else ""
            if not name:
                raise ValueError("name 不能为空")
            fields.append("name = ?")
            params.append(name)
        if "description" in updates:
            description = str(updates["description"] or "").strip()
            fields.append("description = ?")
            params.append(description)
        if "variables" in updates:
            variables = self._normalize_variables(updates["variables"])
            fields.append("variables_json = ?")
            params.append(json.dumps(variables, ensure_ascii=False))
        if not fields:
            raise ValueError("未提供可更新字段")
        fields.append("updated_at = ?")
        params.append(utc_now())
        params.append(collection_id)
        self._db.execute(
            f"UPDATE api_collections SET {', '.join(fields)} WHERE id = ?",
            tuple(params),
        )
        updated = self.get_collection(collection_id)
        if not updated:
            raise ValueError("更新接口集合失败")
        return updated

    def delete_collection(self, collection_id: str) -> bool:
        exists = self._db.fetchone(
            "SELECT id FROM api_collections WHERE id = ? AND deleted_at IS NULL",
            (collection_id,),
        )
        if not exists:
            return False
        now = utc_now()
        self._db.execute(
            "UPDATE api_collections SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now, now, collection_id),
        )
        self._db.execute(
            "UPDATE api_requests SET deleted_at = ?, updated_at = ? WHERE collection_id = ? AND deleted_at IS NULL",
            (now, now, collection_id),
        )
        self._db.execute(
            "UPDATE api_environments SET deleted_at = ?, updated_at = ? WHERE collection_id = ? AND deleted_at IS NULL",
            (now, now, collection_id),
        )
        return True

    def import_openapi(
        self,
        *,
        collection_id: str,
        source_text: str,
        created_by: str | None,
    ) -> dict[str, Any]:
        collection = self.get_collection(collection_id)
        if not collection:
            raise KeyError("collection not found")
        document = self._parse_openapi_document(source_text)
        paths = document.get("paths")
        if not isinstance(paths, dict) or not paths:
            raise ValueError("OpenAPI 文档缺少 paths")

        base_url = self._extract_openapi_base_url(document)
        next_sort = self._next_sort_order(collection_id)
        created_ids: list[str] = []
        warnings: list[str] = []

        for raw_path, path_item in paths.items():
            if not isinstance(path_item, dict):
                warnings.append(f"path {raw_path} 不是对象，已跳过")
                continue
            for raw_method, operation in path_item.items():
                method = str(raw_method).strip().upper()
                if method not in _METHODS:
                    continue
                operation_payload = operation if isinstance(operation, dict) else {}
                try:
                    request_payload = self._build_request_from_openapi(
                        collection_id=collection_id,
                        method=method,
                        path_text=str(raw_path),
                        operation=operation_payload,
                        root=document,
                        base_url=base_url,
                        sort_order=next_sort,
                    )
                    created = self.create_request(payload=request_payload, created_by=created_by)
                    created_ids.append(created["id"])
                    next_sort += 10
                except ValueError as exc:
                    op_name = operation_payload.get("operationId") or f"{method} {raw_path}"
                    warnings.append(f"{op_name}: {exc}")

        return {
            "collectionId": collection_id,
            "created": len(created_ids),
            "requestIds": created_ids,
            "warnings": warnings,
        }

    def export_postman_collection(self, collection_id: str) -> dict[str, Any]:
        collection = self.get_collection(collection_id)
        if not collection:
            raise KeyError("collection not found")
        requests = [item for item in self.list_requests(collection_id) if not item["isFolder"]]
        environments = self.list_environments(collection_id)

        items = [self._to_postman_item(item) for item in requests]
        collection_variables = [
            {"key": key, "value": value}
            for key, value in sorted(collection["variables"].items(), key=lambda pair: pair[0])
        ]
        export = {
            "info": {
                "_postman_id": collection["id"],
                "name": collection["name"],
                "description": collection["description"],
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "item": items,
            "variable": collection_variables,
        }
        postman_envs = [
            {
                "id": env["id"],
                "name": env["name"],
                "values": [
                    {"key": key, "value": value, "type": "default", "enabled": True}
                    for key, value in sorted(env["variables"].items(), key=lambda pair: pair[0])
                ],
                "_postman_variable_scope": "environment",
            }
            for env in environments
        ]
        return {"collection": export, "environments": postman_envs}

    def list_requests(self, collection_id: str) -> list[dict[str, Any]]:
        rows = self._db.fetchall(
            """
            SELECT *
            FROM api_requests
            WHERE collection_id = ? AND deleted_at IS NULL
            ORDER BY sort_order ASC, created_at ASC
            """,
            (collection_id,),
        )
        return [self._row_to_request(item) for item in rows]

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        row = self._db.fetchone(
            """
            SELECT *
            FROM api_requests
            WHERE id = ? AND deleted_at IS NULL
            """,
            (request_id,),
        )
        return self._row_to_request(row) if row else None

    def create_request(
        self,
        *,
        payload: dict[str, Any],
        created_by: str | None,
    ) -> dict[str, Any]:
        collection_id = str(payload["collectionId"]).strip()
        if not self.get_collection(collection_id):
            raise KeyError("collection not found")
        request_id = new_id("areq")
        now = utc_now()
        normalized = self._normalize_request_payload(payload)
        self._db.execute(
            """
            INSERT INTO api_requests (
                id, collection_id, parent_id, name, group_name, tags_json, method, url,
                query_json, headers_json, body_mode, body_raw, body_form_json,
                auth_type, auth_json, verify_ssl, tls_json, tests_json, pre_script, test_script,
                is_folder, sort_order, created_by, deleted_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                collection_id,
                normalized["parentId"],
                normalized["name"],
                normalized["groupName"],
                json.dumps(normalized["tags"], ensure_ascii=False),
                normalized["method"],
                normalized["url"],
                json.dumps(normalized["query"], ensure_ascii=False),
                json.dumps(normalized["headers"], ensure_ascii=False),
                normalized["bodyMode"],
                normalized["bodyRaw"],
                json.dumps(normalized["bodyForm"], ensure_ascii=False),
                normalized["authType"],
                json.dumps(normalized["auth"], ensure_ascii=False),
                1 if normalized["verifySsl"] else 0,
                json.dumps(normalized["tls"], ensure_ascii=False),
                json.dumps(normalized["tests"], ensure_ascii=False),
                normalized["preScript"],
                normalized["testScript"],
                1 if normalized["isFolder"] else 0,
                normalized["sortOrder"],
                created_by,
                None,
                now,
                now,
            ),
        )
        created = self.get_request(request_id)
        if not created:
            raise ValueError("创建接口请求失败")
        return created

    def update_request(
        self,
        *,
        request_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        current = self.get_request(request_id)
        if not current:
            raise KeyError("request not found")
        merged = {**current, **updates}
        normalized = self._normalize_request_payload(merged)
        self._db.execute(
            """
            UPDATE api_requests
            SET parent_id = ?, name = ?, group_name = ?, tags_json = ?, method = ?, url = ?,
                query_json = ?, headers_json = ?, body_mode = ?, body_raw = ?, body_form_json = ?,
                auth_type = ?, auth_json = ?, verify_ssl = ?, tls_json = ?, tests_json = ?, pre_script = ?, test_script = ?,
                is_folder = ?, sort_order = ?, updated_at = ?
            WHERE id = ? AND deleted_at IS NULL
            """,
            (
                normalized["parentId"],
                normalized["name"],
                normalized["groupName"],
                json.dumps(normalized["tags"], ensure_ascii=False),
                normalized["method"],
                normalized["url"],
                json.dumps(normalized["query"], ensure_ascii=False),
                json.dumps(normalized["headers"], ensure_ascii=False),
                normalized["bodyMode"],
                normalized["bodyRaw"],
                json.dumps(normalized["bodyForm"], ensure_ascii=False),
                normalized["authType"],
                json.dumps(normalized["auth"], ensure_ascii=False),
                1 if normalized["verifySsl"] else 0,
                json.dumps(normalized["tls"], ensure_ascii=False),
                json.dumps(normalized["tests"], ensure_ascii=False),
                normalized["preScript"],
                normalized["testScript"],
                1 if normalized["isFolder"] else 0,
                normalized["sortOrder"],
                utc_now(),
                request_id,
            ),
        )
        updated = self.get_request(request_id)
        if not updated:
            raise ValueError("更新接口请求失败")
        return updated

    def delete_request(self, request_id: str) -> bool:
        exists = self._db.fetchone(
            "SELECT id FROM api_requests WHERE id = ? AND deleted_at IS NULL",
            (request_id,),
        )
        if not exists:
            return False
        self._db.execute(
            "UPDATE api_requests SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (utc_now(), utc_now(), request_id),
        )
        return True

    def list_environments(self, collection_id: str) -> list[dict[str, Any]]:
        rows = self._db.fetchall(
            """
            SELECT *
            FROM api_environments
            WHERE collection_id = ? AND deleted_at IS NULL
            ORDER BY is_default DESC, updated_at DESC
            """,
            (collection_id,),
        )
        return [self._row_to_environment(item) for item in rows]

    def get_environment(self, environment_id: str) -> dict[str, Any] | None:
        row = self._db.fetchone(
            """
            SELECT *
            FROM api_environments
            WHERE id = ? AND deleted_at IS NULL
            """,
            (environment_id,),
        )
        return self._row_to_environment(row) if row else None

    def create_environment(
        self,
        *,
        collection_id: str,
        name: str,
        variables: dict[str, str],
        is_default: bool,
        created_by: str | None,
    ) -> dict[str, Any]:
        if not self.get_collection(collection_id):
            raise KeyError("collection not found")
        env_id = new_id("aenv")
        now = utc_now()
        if is_default:
            self._db.execute(
                "UPDATE api_environments SET is_default = 0, updated_at = ? WHERE collection_id = ? AND deleted_at IS NULL",
                (now, collection_id),
            )
        self._db.execute(
            """
            INSERT INTO api_environments (
                id, collection_id, name, variables_json, is_default, created_by, deleted_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                env_id,
                collection_id,
                name.strip(),
                json.dumps(self._normalize_variables(variables), ensure_ascii=False),
                1 if is_default else 0,
                created_by,
                None,
                now,
                now,
            ),
        )
        created = self.get_environment(env_id)
        if not created:
            raise ValueError("创建环境失败")
        return created

    def update_environment(
        self,
        *,
        environment_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        current = self.get_environment(environment_id)
        if not current:
            raise KeyError("environment not found")
        next_name = str(updates.get("name", current["name"])).strip()
        if not next_name:
            raise ValueError("name 不能为空")
        next_variables = self._normalize_variables(updates.get("variables", current["variables"]))
        next_is_default = bool(updates.get("isDefault", current["isDefault"]))
        now = utc_now()
        if next_is_default:
            self._db.execute(
                "UPDATE api_environments SET is_default = 0, updated_at = ? WHERE collection_id = ? AND deleted_at IS NULL",
                (now, current["collectionId"]),
            )
        self._db.execute(
            """
            UPDATE api_environments
            SET name = ?, variables_json = ?, is_default = ?, updated_at = ?
            WHERE id = ? AND deleted_at IS NULL
            """,
            (
                next_name,
                json.dumps(next_variables, ensure_ascii=False),
                1 if next_is_default else 0,
                now,
                environment_id,
            ),
        )
        updated = self.get_environment(environment_id)
        if not updated:
            raise ValueError("更新环境失败")
        return updated

    def delete_environment(self, environment_id: str) -> bool:
        exists = self._db.fetchone(
            "SELECT id FROM api_environments WHERE id = ? AND deleted_at IS NULL",
            (environment_id,),
        )
        if not exists:
            return False
        self._db.execute(
            "UPDATE api_environments SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (utc_now(), utc_now(), environment_id),
        )
        return True

    async def send_request(
        self,
        *,
        request_id: str,
        created_by: str | None,
        environment_id: str | None = None,
        variables: dict[str, str] | None = None,
        timeout_ms: int = 15000,
        verify_ssl: bool = True,
        tls: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_item = self.get_request(request_id)
        if not request_item:
            raise KeyError("request not found")
        runtime_variables = self._normalize_variables(variables or {})
        merged_variables = self._build_variables(
            collection_id=request_item["collectionId"],
            environment_id=environment_id,
            runtime_variables=runtime_variables,
        )
        pre_script_variables = self._apply_pre_script(
            pre_script=request_item.get("preScript", ""),
            variables=merged_variables,
        )
        if pre_script_variables:
            merged_variables.update(pre_script_variables)
        prepared = self._prepare_request(request_item, merged_variables)
        use_loopback_client = self._should_bypass_env_proxy(prepared["url"])
        now = utc_now()
        started = time.perf_counter()
        try:
            response = await self._perform_request(
                prepared=prepared,
                timeout_ms=timeout_ms,
                verify_ssl=verify_ssl,
                use_loopback_client=use_loopback_client,
                tls=tls,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            response_text = response.text
            script_assertions, extracted_variables = self._apply_test_script(
                test_script=request_item.get("testScript", ""),
                response=response,
                duration_ms=duration_ms,
                variables=merged_variables,
            )
            assertions = self._evaluate_assertions(
                tests=[*request_item["tests"], *script_assertions],
                response=response,
                duration_ms=duration_ms,
            )
            success = all(item["passed"] for item in assertions) if assertions else (response.status_code < 400)
            run_meta = {"extractedVariables": extracted_variables}
            run_id = new_id("arun")
            self._db.execute(
                """
                INSERT INTO api_request_runs (
                    id, request_id, collection_id, method, url, status_code, duration_ms, success,
                    response_headers_json, response_body, response_size, error_message, assertions_json, meta_json, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    request_item["id"],
                    request_item["collectionId"],
                    prepared["method"],
                    prepared["url"],
                    int(response.status_code),
                    duration_ms,
                    1 if success else 0,
                    json.dumps(dict(response.headers), ensure_ascii=False),
                    response_text,
                    len(response.content or b""),
                    None,
                    json.dumps(assertions, ensure_ascii=False),
                    json.dumps(run_meta, ensure_ascii=False),
                    created_by,
                    now,
                ),
            )
            run = self.get_run(run_id)
            if not run:
                raise ValueError("保存运行结果失败")
            return run
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            run_id = new_id("arun")
            self._db.execute(
                """
                INSERT INTO api_request_runs (
                    id, request_id, collection_id, method, url, status_code, duration_ms, success,
                    response_headers_json, response_body, response_size, error_message, assertions_json, meta_json, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    request_item["id"],
                    request_item["collectionId"],
                    prepared["method"],
                    prepared["url"],
                    None,
                    duration_ms,
                    0,
                    "{}",
                    "",
                    0,
                    str(exc),
                    "[]",
                    "{}",
                    created_by,
                    now,
                ),
            )
            run = self.get_run(run_id)
            if not run:
                raise ValueError("保存失败运行结果失败")
            return run

    async def run_request(
        self,
        request: Any,
        environment: Any = None,
        variables: dict[str, str] | None = None,
        timeout_ms: int = 15000,
        verify_ssl: bool = True,
        tls: dict[str, Any] | None = None,
    ) -> Any:
        from app.models.api_testing import ApiRequestRunPublic
        
        # 1. 转换输入为字典
        if hasattr(request, "model_dump"):
            request_item = request.model_dump(by_alias=True)
        elif isinstance(request, dict):
            request_item = self._normalize_request_payload(request)
        else:
            request_item = request

        # 2. 合并变量
        runtime_variables = self._normalize_variables(variables or {})
        env_vars = {}
        if environment:
            if hasattr(environment, "variables"):
                env_vars = self._normalize_variables(environment.variables)
            elif isinstance(environment, dict):
                env_vars = self._normalize_variables(environment.get("variables", {}))
        
        merged_variables = {**env_vars, **runtime_variables}
        
        # 3. 前置脚本
        pre_script_updates = self._apply_pre_script(
            pre_script=request_item.get("preScript", ""),
            variables=merged_variables,
        )
        if pre_script_updates:
            merged_variables.update(pre_script_updates)
            
        # 4. 准备与执行
        prepared = self._prepare_request(request_item, merged_variables)
        use_loopback_client = self._should_bypass_env_proxy(prepared["url"])
        started = time.perf_counter()
        try:
            response = await self._perform_request(
                prepared=prepared,
                timeout_ms=timeout_ms,
                verify_ssl=verify_ssl,
                use_loopback_client=use_loopback_client,
                tls=tls,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            
            # 5. 后置脚本与断言
            script_assertions, extracted_variables = self._apply_test_script(
                test_script=request_item.get("testScript", ""),
                response=response,
                duration_ms=duration_ms,
                variables=merged_variables,
            )
            assertions = self._evaluate_assertions(
                tests=[*request_item.get("tests", []), *script_assertions],
                response=response,
                duration_ms=duration_ms,
            )
            success = all(item["passed"] for item in assertions) if assertions else (response.status_code < 400)
            
            return ApiRequestRunPublic(
                id=new_id("arun"),
                requestId=request_item.get("id", "temp"),
                collectionId=request_item.get("collectionId", "temp"),
                method=prepared["method"],
                url=prepared["url"],
                statusCode=response.status_code,
                durationMs=duration_ms,
                success=success,
                responseHeaders=dict(response.headers),
                responseBody=response.text,
                responseSize=len(response.content or b""),
                assertions=assertions,
                extractedVariables=extracted_variables,
                createdAt=utc_now()
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            return ApiRequestRunPublic(
                id=new_id("arun"),
                requestId=request_item.get("id", "temp"),
                collectionId=request_item.get("collectionId", "temp"),
                method=request_item.get("method", "GET"),
                url=request_item.get("url", ""),
                durationMs=duration_ms,
                success=False,
                errorMessage=str(exc),
                createdAt=utc_now()
            )

    async def run_collection(
        self,
        *,
        collection_id: str,
        created_by: str | None,
        environment_id: str | None = None,
        variables: dict[str, str] | None = None,
        group_name: str | None = None,
        request_ids: list[str] | None = None,
        sequential: bool = False,
        timeout_ms: int = 15000,
        verify_ssl: bool = True,
        tls: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.get_collection(collection_id):
            raise KeyError("collection not found")
        requests = [item for item in self.list_requests(collection_id) if not item["isFolder"]]
        if group_name and group_name.strip():
            target_group = group_name.strip()
            requests = [item for item in requests if item.get("groupName") == target_group]
        if request_ids:
            id_set = {str(item).strip() for item in request_ids if str(item).strip()}
            requests = [item for item in requests if item["id"] in id_set]
        if not requests:
            return {
                "collectionId": collection_id,
                "total": 0,
                "passed": 0,
                "failed": 0,
                "runs": [],
            }

        runs: list[dict[str, Any] | None] = [None] * len(requests)
        current_variables = dict(variables or {})

        if sequential:
            # Sequential execution: one by one, passing extracted variables forward
            for index, item in enumerate(requests):
                run = await self.send_request(
                    request_id=item["id"],
                    created_by=created_by,
                    environment_id=environment_id,
                    variables=current_variables,
                    timeout_ms=timeout_ms,
                    verify_ssl=verify_ssl,
                    tls=tls,
                )
                runs[index] = run
                # Update current variables with any variables extracted in this step
                # Note: run['extractedVariables'] is already normalized and stored in the database
                # During the next step, _build_variables will merge them.
                if run.get("extractedVariables"):
                    current_variables.update(run["extractedVariables"])
        else:
            # Parallel execution (default)
            concurrency = max(1, min(4, len(requests)))
            semaphore = asyncio.Semaphore(concurrency)

            async def _run_one(idx: int, req: dict[str, Any]) -> None:
                async with semaphore:
                    runs[idx] = await self.send_request(
                        request_id=req["id"],
                        created_by=created_by,
                        environment_id=environment_id,
                        variables=variables or {},
                        timeout_ms=timeout_ms,
                        verify_ssl=verify_ssl,
                        tls=tls,
                    )

            await asyncio.gather(*(_run_one(i, r) for i, r in enumerate(requests)))

        ordered_runs = [item for item in runs if item is not None]
        passed = sum(1 for item in ordered_runs if item.get("success"))
        failed = len(ordered_runs) - passed
        return {
            "collectionId": collection_id,
            "total": len(requests),
            "passed": passed,
            "failed": failed,
            "runs": ordered_runs,
        }

    async def send_request_batch(
        self,
        *,
        request_id: str,
        created_by: str | None,
        environment_id: str | None = None,
        variable_sets: list[dict[str, Any]],
        timeout_ms: int = 15000,
        verify_ssl: bool = True,
        tls: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_item = self.get_request(request_id)
        if not request_item:
            raise KeyError("request not found")
        if not variable_sets:
            raise ValueError("variableSets 不能为空")
        items: list[dict[str, Any]] = []
        passed = 0
        failed = 0
        for index, item in enumerate(variable_sets):
            item_name = str(item.get("name", "")).strip() or f"dataset-{index + 1}"
            runtime_variables = self._normalize_variables(item.get("variables", {}))
            run = await self.send_request(
                request_id=request_id,
                created_by=created_by,
                environment_id=environment_id,
                variables=runtime_variables,
                timeout_ms=timeout_ms,
                verify_ssl=verify_ssl,
                tls=tls,
            )
            items.append({"name": item_name, "variables": runtime_variables, "run": run})
            if run["success"]:
                passed += 1
            else:
                failed += 1
        return {
            "requestId": request_id,
            "total": len(items),
            "passed": passed,
            "failed": failed,
            "items": items,
        }

    def list_runs(
        self,
        *,
        collection_id: str | None = None,
        request_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if collection_id:
            conditions.append("collection_id = ?")
            params.append(collection_id)
        if request_id:
            conditions.append("request_id = ?")
            params.append(request_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._db.fetchall(
            f"""
            SELECT *
            FROM api_request_runs
            {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            tuple([*params, max(min(limit, 300), 1)]),
        )
        return [self._row_to_run(item) for item in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._db.fetchone(
            """
            SELECT *
            FROM api_request_runs
            WHERE id = ?
            """,
            (run_id,),
        )
        return self._row_to_run(row) if row else None

    def _build_variables(
        self,
        *,
        collection_id: str,
        environment_id: str | None,
        runtime_variables: dict[str, str],
    ) -> dict[str, str]:
        resolved: dict[str, str] = {}
        collection = self.get_collection(collection_id)
        if collection:
            resolved.update({k: str(v) for k, v in collection["variables"].items()})
        env: dict[str, Any] | None = None
        if environment_id:
            env = self.get_environment(environment_id)
        if env is None:
            rows = self.list_environments(collection_id)
            env = next((item for item in rows if item["isDefault"]), rows[0] if rows else None)
        if env:
            resolved.update({k: str(v) for k, v in env["variables"].items()})
        resolved.update({str(k): str(v) for k, v in runtime_variables.items()})
        return resolved

    def _prepare_request(self, request_item: dict[str, Any], variables: dict[str, str]) -> dict[str, Any]:
        method = request_item["method"].upper()
        url = self._resolve_templates(request_item["url"], variables).strip()
        if not url:
            raise ValueError("请求 URL 不能为空")
        unresolved = sorted({match.group(1) for match in _TEMPLATE_PATTERN.finditer(url)})
        if unresolved:
            joined = ", ".join(unresolved)
            raise ValueError(f"URL 存在未解析变量: {joined}，请在环境变量或运行时变量中补齐")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("请求 URL 必须以 http:// 或 https:// 开头")
        if not parsed.netloc:
            raise ValueError("请求 URL 缺少主机名")
        headers = self._kv_list_to_dict(request_item["headers"], variables)
        params = self._kv_list_to_list(request_item["query"], variables)
        auth = None
        auth_type = request_item["authType"]
        auth_config = request_item["auth"]
        if auth_type == "bearer":
            token = self._resolve_templates(str(auth_config.get("token", "")), variables).strip()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "basic":
            username = self._resolve_templates(str(auth_config.get("username", "")), variables)
            password = self._resolve_templates(str(auth_config.get("password", "")), variables)
            auth = (username, password)
        elif auth_type == "apiKey":
            key = str(auth_config.get("key", "")).strip()
            value = self._resolve_templates(str(auth_config.get("value", "")), variables)
            target = str(auth_config.get("in", "header")).strip().lower()
            if key and target == "query":
                params.append((key, value))
            elif key:
                headers[key] = value

        body_mode = request_item["bodyMode"]
        body_raw = self._resolve_templates(request_item["bodyRaw"], variables)
        body_form = self._kv_list_to_dict(request_item["bodyForm"], variables)
        json_body: Any = None
        data_body: Any = None
        raw_body: bytes | None = None
        if body_mode == "json":
            try:
                json_body = json.loads(body_raw) if body_raw.strip() else {}
            except json.JSONDecodeError:
                raw_body = body_raw.encode("utf-8")
                headers.setdefault("Content-Type", "application/json; charset=utf-8")
        elif body_mode == "raw":
            raw_body = body_raw.encode("utf-8")
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")
        elif body_mode == "form":
            data_body = body_form

        return {
            "method": method,
            "url": url,
            "params": params,
            "headers": headers,
            "auth": auth,
            "json_body": json_body,
            "data_body": data_body,
            "raw_body": raw_body,
        }

    @staticmethod
    def _should_bypass_env_proxy(url: str) -> bool:
        hostname = (urlparse(url).hostname or "").strip().lower().rstrip(".")
        if not hostname:
            return False
        if hostname == "localhost" or hostname.endswith(".localhost"):
            return True
        try:
            return ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            return False

    async def _perform_request(
        self,
        *,
        prepared: dict[str, Any],
        timeout_ms: int,
        verify_ssl: bool,
        use_loopback_client: bool,
        tls: dict[str, Any] | None,
    ) -> httpx.Response:
        request_kwargs = {
            "method": prepared["method"],
            "url": prepared["url"],
            "params": prepared["params"],
            "headers": prepared["headers"],
            "auth": prepared["auth"],
            "json": prepared["json_body"],
            "data": prepared["data_body"],
            "content": prepared["raw_body"],
            "timeout": max(timeout_ms / 1000.0, 0.5),
        }
        cert, temp_dir = self._resolve_client_cert(tls)
        try:
            if cert is None:
                if use_loopback_client:
                    http_client = self._loopback_http_client if verify_ssl else self._loopback_http_client_insecure
                else:
                    http_client = self._http_client if verify_ssl else self._http_client_insecure
                return await http_client.request(**request_kwargs)

            async with httpx.AsyncClient(
                follow_redirects=False,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
                verify=verify_ssl,
                cert=cert,
                trust_env=not use_loopback_client,
            ) as client:
                return await client.request(**request_kwargs)
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _resolve_client_cert(tls: dict[str, Any] | None) -> tuple[Any | None, Path | None]:
        if not isinstance(tls, dict):
            return None, None
        cert_pem = str(tls.get("certPem") or tls.get("certContent") or "").strip()
        key_pem = str(tls.get("keyPem") or tls.get("keyContent") or "").strip()
        if cert_pem or key_pem:
            if not cert_pem:
                raise ValueError("已提供客户端私钥，但缺少证书文件 certPem")
            temp_dir = Path(tempfile.mkdtemp(prefix="ai-mtls-"))
            cert_file_path = temp_dir / "client-cert.pem"
            cert_file_path.write_text(cert_pem, encoding="utf-8")
            if key_pem:
                key_file_path = temp_dir / "client-key.pem"
                key_file_path.write_text(key_pem, encoding="utf-8")
                return (str(cert_file_path), str(key_file_path)), temp_dir
            return str(cert_file_path), temp_dir
        cert_file = str(tls.get("certFile") or tls.get("certPath") or "").strip()
        key_file = str(tls.get("keyFile") or tls.get("keyPath") or "").strip()
        if not cert_file and not key_file:
            return None, None
        if cert_file and not Path(cert_file).exists():
            raise ValueError(f"客户端证书文件不存在: {cert_file}")
        if key_file and not Path(key_file).exists():
            raise ValueError(f"客户端私钥文件不存在: {key_file}")
        if cert_file and key_file:
            return (cert_file, key_file), None
        if cert_file:
            return cert_file, None
        raise ValueError("已提供客户端私钥，但缺少证书文件 certFile")

    def _apply_pre_script(self, *, pre_script: str, variables: dict[str, str]) -> dict[str, str]:
        text = str(pre_script or "").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        context = {
            **variables,
            "nowIso": utc_now(),
            "nowTs": str(int(time.time())),
            "uuid": uuid4().hex,
        }
        updates: dict[str, str] = {}
        set_items = payload.get("set", {})
        if isinstance(set_items, dict):
            for key, value in set_items.items():
                text_key = str(key).strip()
                if not text_key:
                    continue
                resolved_value = self._resolve_templates(str(value), context)
                updates[text_key] = resolved_value
                context[text_key] = resolved_value
        unset_items = payload.get("unset", [])
        if isinstance(unset_items, list):
            for key in unset_items:
                text_key = str(key).strip()
                if not text_key:
                    continue
                updates.pop(text_key, None)
        return updates

    def _apply_test_script(
        self,
        *,
        test_script: str,
        response: httpx.Response,
        duration_ms: int,
        variables: dict[str, str],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        text = str(test_script or "").strip()
        if not text:
            return [], {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return [], {}
        if not isinstance(payload, dict):
            return [], {}

        extra_assertions = payload.get("assert", [])
        assertions: list[dict[str, Any]] = []
        if isinstance(extra_assertions, list):
            for item in extra_assertions:
                if not isinstance(item, dict):
                    continue
                normalized: dict[str, Any] = {}
                for key, value in item.items():
                    if isinstance(value, str):
                        normalized[str(key)] = self._resolve_templates(value, variables)
                    else:
                        normalized[str(key)] = value
                assertions.append(normalized)

        extracted: dict[str, str] = {}
        extract_items = payload.get("extract", [])
        if not isinstance(extract_items, list):
            return assertions, extracted

        json_payload: Any = None
        for item in extract_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            source = str(item.get("from", "json")).strip().lower()
            if source == "header":
                key = str(item.get("key", "")).strip().lower()
                if not key:
                    continue
                value = response.headers.get(key)
                if value is not None:
                    extracted[name] = str(value)
                continue
            if source == "duration":
                extracted[name] = str(duration_ms)
                continue
            if source == "variable":
                key = str(item.get("key", "")).strip()
                if key and key in variables:
                    extracted[name] = str(variables[key])
                continue
            if json_payload is None:
                try:
                    json_payload = response.json()
                except Exception:
                    json_payload = "__invalid_json__"
            if json_payload == "__invalid_json__":
                continue
            path = str(item.get("path", "")).strip()
            value = self._read_json_path(json_payload, path)
            if value is None:
                continue
            extracted[name] = str(value)
        return assertions, extracted

    def _evaluate_assertions(
        self,
        *,
        tests: list[dict[str, Any]],
        response: httpx.Response,
        duration_ms: int,
    ) -> list[dict[str, Any]]:
        if not tests:
            return []
        result: list[dict[str, Any]] = []
        json_payload: Any = None
        response_text = response.text
        for item in tests:
            test_type = str(item.get("type", "")).strip()
            test_name = str(item.get("name", "")).strip() or None
            if test_type == "status_eq":
                expected = int(item.get("expected", 200))
                passed = int(response.status_code) == expected
                message = f"expect {expected}, got {response.status_code}"
            elif test_type == "status_range":
                min_status = int(item.get("min", 200))
                max_status = int(item.get("max", 299))
                passed = min_status <= int(response.status_code) <= max_status
                message = f"expect {min_status}-{max_status}, got {response.status_code}"
            elif test_type == "response_time_lt":
                expected = int(item.get("expectedMs", 1000))
                passed = duration_ms < expected
                message = f"expect < {expected}ms, got {duration_ms}ms"
            elif test_type == "header_contains":
                key = str(item.get("key", "")).strip().lower()
                expected = str(item.get("contains", ""))
                got = response.headers.get(key, "")
                passed = expected in got
                message = f"expect header {key} contains {expected}"
            elif test_type == "header_eq":
                key = str(item.get("key", "")).strip().lower()
                expected = str(item.get("expected", ""))
                got = response.headers.get(key, "")
                passed = got == expected
                message = f"expect header {key} == {expected}, got {got}"
            elif test_type == "body_contains":
                expected = str(item.get("contains", ""))
                passed = expected in response_text
                message = f"expect body contains {expected}"
            elif test_type == "json_path_eq":
                path = str(item.get("path", "")).strip()
                expected = item.get("expected")
                if json_payload is None:
                    try:
                        json_payload = response.json()
                    except Exception:
                        json_payload = "__invalid_json__"
                if json_payload == "__invalid_json__":
                    passed = False
                    message = "response is not valid json"
                else:
                    actual = self._read_json_path(json_payload, path)
                    passed = actual == expected
                    message = f"expect {path} == {expected}, got {actual}"
            elif test_type == "json_path_exists":
                path = str(item.get("path", "")).strip()
                if json_payload is None:
                    try:
                        json_payload = response.json()
                    except Exception:
                        json_payload = "__invalid_json__"
                if json_payload == "__invalid_json__":
                    passed = False
                    message = "response is not valid json"
                else:
                    actual = self._read_json_path(json_payload, path)
                    passed = actual is not None
                    message = f"expect {path} exists"
            elif test_type == "json_path_contains":
                path = str(item.get("path", "")).strip()
                expected_contains = item.get("contains")
                if json_payload is None:
                    try:
                        json_payload = response.json()
                    except Exception:
                        json_payload = "__invalid_json__"
                if json_payload == "__invalid_json__":
                    passed = False
                    message = "response is not valid json"
                else:
                    actual = self._read_json_path(json_payload, path)
                    if isinstance(actual, list):
                        passed = expected_contains in actual
                    elif isinstance(actual, str):
                        passed = str(expected_contains) in actual
                    else:
                        passed = str(expected_contains) in json.dumps(actual, ensure_ascii=False)
                    message = f"expect {path} contains {expected_contains}, got {actual}"
            else:
                passed = False
                message = f"unsupported assertion type: {test_type}"
            result.append(
                {
                    "type": test_type or "status_eq",
                    "passed": bool(passed),
                    "message": message,
                    "name": test_name,
                }
            )
        return result

    @staticmethod
    def _read_json_path(payload: Any, path: str) -> Any:
        if not path:
            return payload
        current = payload
        for part in path.split("."):
            token = part.strip()
            if not token:
                continue
            if isinstance(current, dict):
                current = current.get(token)
            elif isinstance(current, list) and token.isdigit():
                index = int(token)
                if index < 0 or index >= len(current):
                    return None
                current = current[index]
            else:
                return None
        return current

    @staticmethod
    def _resolve_templates(text: str, variables: dict[str, str]) -> str:
        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            return variables.get(key, match.group(0))

        return _TEMPLATE_PATTERN.sub(_replace, text)

    def _normalize_request_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        url = str(payload.get("url", "")).strip()
        method = str(payload.get("method", "GET")).upper()
        if not name:
            raise ValueError("name 不能为空")
        if not url:
            raise ValueError("url 不能为空")
        if method not in _METHODS:
            raise ValueError("method 非法")
        body_mode = str(payload.get("bodyMode", "none")).strip()
        if body_mode not in _BODY_MODES:
            raise ValueError("bodyMode 非法")
        auth_type = str(payload.get("authType", "none")).strip()
        if auth_type not in _AUTH_TYPES:
            raise ValueError("authType 非法")
        return {
            "collectionId": str(payload.get("collectionId", "")).strip(),
            "parentId": str(payload.get("parentId", "")).strip() or None,
            "name": name,
            "groupName": str(payload.get("groupName", "default")).strip() or "default",
            "tags": self._normalize_tags(payload.get("tags", [])),
            "method": method,
            "url": url,
            "query": self._normalize_kv_list(payload.get("query", [])),
            "headers": self._normalize_kv_list(payload.get("headers", [])),
            "bodyMode": body_mode,
            "bodyRaw": str(payload.get("bodyRaw", "")),
            "bodyForm": self._normalize_kv_list(payload.get("bodyForm", [])),
            "authType": auth_type,
            "auth": payload.get("auth", {}) if isinstance(payload.get("auth"), dict) else {},
            "verifySsl": bool(payload.get("verifySsl", True)),
            "tls": payload.get("tls", {}) if isinstance(payload.get("tls"), dict) else {},
            "tests": payload.get("tests", []) if isinstance(payload.get("tests"), list) else [],
            "preScript": str(payload.get("preScript", "")),
            "testScript": str(payload.get("testScript", "")),
            "isFolder": bool(payload.get("isFolder", False)),
            "sortOrder": int(payload.get("sortOrder", 0) or 0),
        }

    @staticmethod
    def _normalize_variables(raw: Any) -> dict[str, str]:
        if not isinstance(raw, dict):
            return {}
        result: dict[str, str] = {}
        for key, value in raw.items():
            text_key = str(key).strip()
            if not text_key:
                continue
            result[text_key] = str(value)
        return result

    @staticmethod
    def _normalize_kv_list(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        result: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip()
            value = str(item.get("value", ""))
            enabled = bool(item.get("enabled", True))
            description = str(item.get("description", ""))
            if not key and not value and not description:
                continue
            result.append(
                {
                    "key": key,
                    "value": value,
                    "enabled": enabled,
                    "description": description,
                }
            )
        return result

    @staticmethod
    def _normalize_tags(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in raw:
            text = str(item).strip()
            if not text:
                continue
            lowered = text.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            result.append(text)
        return result

    def _kv_list_to_dict(self, items: list[dict[str, Any]], variables: dict[str, str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for item in items:
            if not item.get("enabled", True):
                continue
            key = str(item.get("key", "")).strip()
            if not key:
                continue
            value = self._resolve_templates(str(item.get("value", "")), variables)
            result[key] = value
        return result

    def _kv_list_to_list(self, items: list[dict[str, Any]], variables: dict[str, str]) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for item in items:
            if not item.get("enabled", True):
                continue
            key = str(item.get("key", "")).strip()
            if not key:
                continue
            value = self._resolve_templates(str(item.get("value", "")), variables)
            result.append((key, value))
        return result

    def _next_sort_order(self, collection_id: str) -> int:
        row = self._db.fetchone(
            """
            SELECT MAX(sort_order) AS max_sort
            FROM api_requests
            WHERE collection_id = ? AND deleted_at IS NULL
            """,
            (collection_id,),
        )
        current_max = int(row.get("max_sort") or 0) if row else 0
        return current_max + 10

    def _parse_openapi_document(self, source_text: str) -> dict[str, Any]:
        text = source_text.strip()
        if not text:
            raise ValueError("OpenAPI 内容为空")
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            if yaml is None:
                raise ValueError("OpenAPI 解析失败：当前仅支持 JSON，若要导入 YAML 请先安装 pyyaml") from None
            try:
                decoded = yaml.safe_load(text)  # type: ignore[union-attr]
            except Exception as exc:
                raise ValueError("OpenAPI 解析失败，请检查 JSON/YAML 格式是否正确") from exc
        if not isinstance(decoded, dict):
            raise ValueError("OpenAPI 根节点必须是对象")
        return decoded

    @staticmethod
    def _extract_openapi_base_url(document: dict[str, Any]) -> str:
        servers = document.get("servers")
        if isinstance(servers, list):
            for item in servers:
                if isinstance(item, dict):
                    url = str(item.get("url", "")).strip()
                    if url:
                        return url.rstrip("/")
        return ""

    @staticmethod
    def _openapi_path_to_template(path_text: str) -> str:
        return re.sub(r"{\s*([^{}\s]+)\s*}", r"{{\1}}", path_text)

    def _build_request_from_openapi(
        self,
        *,
        collection_id: str,
        method: str,
        path_text: str,
        operation: dict[str, Any],
        root: dict[str, Any],
        base_url: str,
        sort_order: int,
    ) -> dict[str, Any]:
        normalized_path = self._openapi_path_to_template(path_text.strip() or "/")
        if base_url:
            if normalized_path.startswith("http://") or normalized_path.startswith("https://"):
                target_url = normalized_path
            else:
                target_url = f"{base_url}/{normalized_path.lstrip('/')}"
        else:
            target_url = normalized_path

        name = str(
            operation.get("summary")
            or operation.get("operationId")
            or f"{method} {normalized_path}"
        ).strip()
        if not name:
            raise ValueError("缺少接口名称")

        query: list[dict[str, Any]] = []
        headers: list[dict[str, Any]] = []
        path_node = root.get("paths", {}).get(path_text, {})
        path_parameters = path_node.get("parameters", []) if isinstance(path_node, dict) else []
        operation_parameters = operation.get("parameters", [])
        for raw_param in [*path_parameters, *operation_parameters]:
            if not isinstance(raw_param, dict):
                continue
            param = self._resolve_openapi_ref(raw_param, root)
            if not isinstance(param, dict):
                continue
            key = str(param.get("name", "")).strip()
            location = str(param.get("in", "")).strip().lower()
            if not key or location not in {"query", "header"}:
                continue
            value = param.get("example")
            schema = param.get("schema")
            if value is None and isinstance(schema, dict):
                value = schema.get("default")
            if value is None and isinstance(schema, dict):
                value = self._schema_to_example(schema, root)
            entry = {
                "key": key,
                "value": str(value) if value is not None else "",
                "enabled": True,
                "description": str(param.get("description", "")),
            }
            if location == "query":
                query.append(entry)
            else:
                headers.append(entry)

        body_mode, body_raw, body_form, body_warnings = self._build_body_from_openapi(
            request_body=operation.get("requestBody"),
            root=root,
        )
        if body_warnings:
            headers.append(
                {
                    "key": "X-AI-Import-Warning",
                    "value": "; ".join(body_warnings)[:500],
                    "enabled": False,
                    "description": "OpenAPI 导入提示",
                }
            )

        auth_type, auth = self._extract_openapi_auth(operation, root)
        expected_status = self._pick_openapi_success_status(operation.get("responses"))
        tests = [{"type": "status_eq", "name": "HTTP 状态码", "expected": expected_status}]

        return {
            "collectionId": collection_id,
            "name": name,
            "method": method,
            "url": target_url,
            "query": query,
            "headers": headers,
            "bodyMode": body_mode,
            "bodyRaw": body_raw,
            "bodyForm": body_form,
            "authType": auth_type,
            "auth": auth,
            "tests": tests,
            "preScript": "",
            "testScript": "",
            "isFolder": False,
            "sortOrder": sort_order,
        }

    def _build_body_from_openapi(
        self,
        *,
        request_body: Any,
        root: dict[str, Any],
    ) -> tuple[str, str, list[dict[str, Any]], list[str]]:
        if not isinstance(request_body, dict):
            return "none", "", [], []
        body_spec = self._resolve_openapi_ref(request_body, root)
        if not isinstance(body_spec, dict):
            return "none", "", [], []
        content = body_spec.get("content")
        if not isinstance(content, dict) or not content:
            return "none", "", [], []

        warnings: list[str] = []
        if "application/json" in content:
            media = content.get("application/json")
            media_obj = media if isinstance(media, dict) else {}
            example = media_obj.get("example")
            if example is None and isinstance(media_obj.get("examples"), dict):
                for item in media_obj["examples"].values():
                    if isinstance(item, dict) and "value" in item:
                        example = item["value"]
                        break
            schema = media_obj.get("schema")
            if example is None and isinstance(schema, dict):
                example = self._schema_to_example(schema, root)
            if example is None:
                example = {}
            return "json", json.dumps(example, ensure_ascii=False, indent=2), [], warnings

        for content_type in ["application/x-www-form-urlencoded", "multipart/form-data"]:
            if content_type not in content:
                continue
            media = content.get(content_type)
            media_obj = media if isinstance(media, dict) else {}
            schema = media_obj.get("schema")
            form_items: list[dict[str, Any]] = []
            if isinstance(schema, dict):
                resolved_schema = self._resolve_openapi_ref(schema, root)
                props = resolved_schema.get("properties", {}) if isinstance(resolved_schema, dict) else {}
                if isinstance(props, dict):
                    for key, prop in props.items():
                        if not isinstance(key, str):
                            continue
                        prop_obj = prop if isinstance(prop, dict) else {}
                        sample = self._schema_to_example(prop_obj, root)
                        form_items.append(
                            {
                                "key": key,
                                "value": "" if sample is None else str(sample),
                                "enabled": True,
                                "description": str(prop_obj.get("description", "")),
                            }
                        )
            return "form", "", form_items, warnings

        if "text/plain" in content:
            media = content.get("text/plain")
            media_obj = media if isinstance(media, dict) else {}
            example = media_obj.get("example")
            if example is None:
                example = ""
            return "raw", str(example), [], warnings

        warnings.append(f"不支持的 content-type: {', '.join(content.keys())}")
        return "none", "", [], warnings

    def _extract_openapi_auth(
        self,
        operation: dict[str, Any],
        root: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        raw_security = operation.get("security")
        if raw_security is None:
            raw_security = root.get("security")
        if not isinstance(raw_security, list):
            return "none", {}
        schemes = (
            root.get("components", {}).get("securitySchemes", {})
            if isinstance(root.get("components"), dict)
            else {}
        )
        if not isinstance(schemes, dict):
            return "none", {}

        for item in raw_security:
            if not isinstance(item, dict):
                continue
            for scheme_name in item.keys():
                scheme = schemes.get(scheme_name)
                if not isinstance(scheme, dict):
                    continue
                security_type = str(scheme.get("type", "")).strip()
                if security_type == "http":
                    kind = str(scheme.get("scheme", "")).strip().lower()
                    if kind == "bearer":
                        return "bearer", {"token": "{{token}}"}
                    if kind == "basic":
                        return "basic", {"username": "{{username}}", "password": "{{password}}"}
                if security_type == "apiKey":
                    key_name = str(scheme.get("name", "")).strip() or "X-API-Key"
                    key_in = str(scheme.get("in", "header")).strip().lower()
                    return "apiKey", {"key": key_name, "value": "{{apiKey}}", "in": key_in}
        return "none", {}

    @staticmethod
    def _pick_openapi_success_status(responses: Any) -> int:
        if not isinstance(responses, dict):
            return 200
        candidates: list[int] = []
        for key in responses.keys():
            raw = str(key).strip()
            if raw.isdigit():
                code = int(raw)
                if 200 <= code < 300:
                    candidates.append(code)
        return min(candidates) if candidates else 200

    def _resolve_openapi_ref(self, value: Any, root: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        ref = value.get("$ref")
        if not ref:
            return value
        ref_text = str(ref)
        if not ref_text.startswith("#/"):
            return {}
        node: Any = root
        for token in ref_text[2:].split("/"):
            if not isinstance(node, dict):
                return {}
            node = node.get(token)
        return node if isinstance(node, dict) else {}

    def _schema_to_example(self, schema: Any, root: dict[str, Any]) -> Any:
        if not isinstance(schema, dict):
            return None
        resolved = self._resolve_openapi_ref(schema, root)
        if not resolved:
            resolved = schema
        if "example" in resolved:
            return resolved["example"]
        if "default" in resolved:
            return resolved["default"]
        if isinstance(resolved.get("enum"), list) and resolved["enum"]:
            return resolved["enum"][0]
        if isinstance(resolved.get("oneOf"), list) and resolved["oneOf"]:
            return self._schema_to_example(resolved["oneOf"][0], root)
        if isinstance(resolved.get("anyOf"), list) and resolved["anyOf"]:
            return self._schema_to_example(resolved["anyOf"][0], root)

        schema_type = str(resolved.get("type", "")).strip().lower()
        if schema_type == "object":
            props = resolved.get("properties", {})
            if not isinstance(props, dict):
                return {}
            return {str(key): self._schema_to_example(prop, root) for key, prop in props.items()}
        if schema_type == "array":
            item_schema = resolved.get("items", {})
            return [self._schema_to_example(item_schema, root)]
        if schema_type == "integer":
            return 0
        if schema_type == "number":
            return 0
        if schema_type == "boolean":
            return False
        if schema_type == "string":
            fmt = str(resolved.get("format", "")).strip().lower()
            if fmt == "date-time":
                return utc_now()
            if fmt == "date":
                return utc_now()[:10]
            return ""
        return None

    def _to_postman_item(self, request_item: dict[str, Any]) -> dict[str, Any]:
        raw_url = str(request_item.get("url") or "")
        url_payload: dict[str, Any] = {"raw": raw_url}
        if raw_url.startswith("http://") or raw_url.startswith("https://"):
            parsed = urlparse(raw_url)
            if parsed.scheme:
                url_payload["protocol"] = parsed.scheme
            if parsed.netloc:
                url_payload["host"] = [part for part in parsed.netloc.split(".") if part]
            if parsed.path:
                url_payload["path"] = [part for part in parsed.path.split("/") if part]
        else:
            path_only = raw_url.split("?", 1)[0]
            url_payload["path"] = [part for part in path_only.split("/") if part]

        query_items = []
        for item in request_item.get("query", []):
            if not item.get("enabled", True):
                continue
            key = str(item.get("key", "")).strip()
            if not key:
                continue
            query_items.append({"key": key, "value": str(item.get("value", ""))})
        if query_items:
            url_payload["query"] = query_items

        header_items = []
        for item in request_item.get("headers", []):
            if not item.get("enabled", True):
                continue
            key = str(item.get("key", "")).strip()
            if not key:
                continue
            header_items.append({"key": key, "value": str(item.get("value", ""))})

        request_payload: dict[str, Any] = {
            "method": request_item.get("method", "GET"),
            "header": header_items,
            "url": url_payload,
        }
        body_payload = self._to_postman_body(request_item)
        if body_payload is not None:
            request_payload["body"] = body_payload
        auth_payload = self._to_postman_auth(request_item)
        if auth_payload is not None:
            request_payload["auth"] = auth_payload
        script_event = self._to_postman_test_event(request_item.get("tests", []))
        item_payload: dict[str, Any] = {
            "name": request_item.get("name", ""),
            "request": request_payload,
            "response": [],
        }
        if script_event is not None:
            item_payload["event"] = [script_event]
        return item_payload

    @staticmethod
    def _to_postman_auth(request_item: dict[str, Any]) -> dict[str, Any] | None:
        auth_type = str(request_item.get("authType", "none"))
        auth = request_item.get("auth", {})
        auth_obj = auth if isinstance(auth, dict) else {}
        if auth_type == "bearer":
            return {
                "type": "bearer",
                "bearer": [{"key": "token", "value": str(auth_obj.get("token", "")), "type": "string"}],
            }
        if auth_type == "basic":
            return {
                "type": "basic",
                "basic": [
                    {"key": "username", "value": str(auth_obj.get("username", "")), "type": "string"},
                    {"key": "password", "value": str(auth_obj.get("password", "")), "type": "string"},
                ],
            }
        if auth_type == "apiKey":
            return {
                "type": "apikey",
                "apikey": [
                    {"key": "key", "value": str(auth_obj.get("key", "")), "type": "string"},
                    {"key": "value", "value": str(auth_obj.get("value", "")), "type": "string"},
                    {"key": "in", "value": str(auth_obj.get("in", "header")), "type": "string"},
                ],
            }
        return None

    @staticmethod
    def _to_postman_body(request_item: dict[str, Any]) -> dict[str, Any] | None:
        body_mode = str(request_item.get("bodyMode", "none"))
        if body_mode == "none":
            return None
        if body_mode in {"raw", "json"}:
            raw = str(request_item.get("bodyRaw", ""))
            language = "json" if body_mode == "json" else "text"
            return {"mode": "raw", "raw": raw, "options": {"raw": {"language": language}}}
        if body_mode == "form":
            form_items = []
            for item in request_item.get("bodyForm", []):
                if not item.get("enabled", True):
                    continue
                key = str(item.get("key", "")).strip()
                if not key:
                    continue
                form_items.append({"key": key, "value": str(item.get("value", "")), "type": "text"})
            return {"mode": "urlencoded", "urlencoded": form_items}
        return None

    @staticmethod
    def _to_postman_test_event(tests: Any) -> dict[str, Any] | None:
        if not isinstance(tests, list) or not tests:
            return None
        lines = [
            "// Imported from AI Test Platform",
            "function readPath(payload, path) {",
            "  if (!path) return payload;",
            "  return path.split('.').reduce((acc, part) => (acc == null ? null : acc[part]), payload);",
            "}",
        ]
        for item in tests:
            if not isinstance(item, dict):
                continue
            test_type = str(item.get("type", "")).strip()
            test_name = str(item.get("name", "")).strip() or test_type or "assertion"
            safe_name = json.dumps(test_name, ensure_ascii=False)
            if test_type == "status_eq":
                expected = int(item.get("expected", 200))
                lines.append(
                    f"pm.test({safe_name}, function () {{ pm.response.to.have.status({expected}); }});"
                )
            elif test_type == "status_range":
                min_status = int(item.get("min", 200))
                max_status = int(item.get("max", 299))
                lines.append(
                    "pm.test("
                    + safe_name
                    + ", function () { const s = pm.response.code; pm.expect(s >= "
                    + str(min_status)
                    + " && s <= "
                    + str(max_status)
                    + ").to.eql(true); });"
                )
            elif test_type == "response_time_lt":
                expected_ms = int(item.get("expectedMs", 1000))
                lines.append(
                    f"pm.test({safe_name}, function () {{ pm.expect(pm.response.responseTime).to.be.below({expected_ms}); }});"
                )
            elif test_type == "header_contains":
                key = json.dumps(str(item.get("key", "")), ensure_ascii=False)
                contains = json.dumps(str(item.get("contains", "")), ensure_ascii=False)
                lines.append(
                    "pm.test("
                    + safe_name
                    + ", function () { pm.expect(pm.response.headers.get("
                    + key
                    + ") || '').to.include("
                    + contains
                    + "); });"
                )
            elif test_type == "header_eq":
                key = json.dumps(str(item.get("key", "")), ensure_ascii=False)
                expected = json.dumps(str(item.get("expected", "")), ensure_ascii=False)
                lines.append(
                    "pm.test("
                    + safe_name
                    + ", function () { pm.expect(pm.response.headers.get("
                    + key
                    + ") || '').to.eql("
                    + expected
                    + "); });"
                )
            elif test_type == "body_contains":
                contains = json.dumps(str(item.get("contains", "")), ensure_ascii=False)
                lines.append(
                    "pm.test("
                    + safe_name
                    + ", function () { pm.expect(pm.response.text()).to.include("
                    + contains
                    + "); });"
                )
            elif test_type == "json_path_eq":
                path = json.dumps(str(item.get("path", "")), ensure_ascii=False)
                expected = json.dumps(item.get("expected"), ensure_ascii=False)
                lines.append(
                    "pm.test("
                    + safe_name
                    + ", function () { const payload = pm.response.json(); pm.expect(readPath(payload, "
                    + path
                    + ")).to.eql("
                    + expected
                    + "); });"
                )
            elif test_type == "json_path_exists":
                path = json.dumps(str(item.get("path", "")), ensure_ascii=False)
                lines.append(
                    "pm.test("
                    + safe_name
                    + ", function () { const payload = pm.response.json(); pm.expect(readPath(payload, "
                    + path
                    + ")).to.not.eql(undefined); });"
                )
            elif test_type == "json_path_contains":
                path = json.dumps(str(item.get("path", "")), ensure_ascii=False)
                contains = json.dumps(item.get("contains"), ensure_ascii=False)
                lines.append(
                    "pm.test("
                    + safe_name
                    + ", function () { const payload = pm.response.json(); const value = readPath(payload, "
                    + path
                    + "); pm.expect(String(value)).to.include(String("
                    + contains
                    + ")); });"
                )
            else:
                lines.append(f"// Unsupported assertion in source: {test_type}")
        return {
            "listen": "test",
            "script": {
                "type": "text/javascript",
                "exec": lines,
            },
        }

    def _row_to_collection(self, row: dict[str, Any]) -> dict[str, Any]:
        variables = self._parse_json_dict(row.get("variables_json"), default={})
        return {
            "id": row["id"],
            "projectId": row["project_id"],
            "name": row["name"],
            "description": row.get("description") or "",
            "variables": {str(k): str(v) for k, v in variables.items()},
            "createdBy": row.get("created_by"),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _row_to_request(self, row: dict[str, Any]) -> dict[str, Any]:
        tags = self._parse_json_list(row.get("tags_json"), default=[])
        normalized_tags = [str(item).strip() for item in tags if str(item).strip()]
        return {
            "id": row["id"],
            "collectionId": row["collection_id"],
            "parentId": row.get("parent_id"),
            "name": row["name"],
            "groupName": str(row.get("group_name") or "default"),
            "tags": normalized_tags,
            "method": str(row.get("method", "GET")).upper(),
            "url": row.get("url") or "",
            "query": self._parse_json_list(row.get("query_json"), default=[]),
            "headers": self._parse_json_list(row.get("headers_json"), default=[]),
            "bodyMode": row.get("body_mode") or "none",
            "bodyRaw": row.get("body_raw") or "",
            "bodyForm": self._parse_json_list(row.get("body_form_json"), default=[]),
            "authType": row.get("auth_type") or "none",
            "auth": self._parse_json_dict(row.get("auth_json"), default={}),
            "verifySsl": bool(row.get("verify_ssl", 1)),
            "tls": self._parse_json_dict(row.get("tls_json"), default={}),
            "tests": self._parse_json_list(row.get("tests_json"), default=[]),
            "preScript": row.get("pre_script") or "",
            "testScript": row.get("test_script") or "",
            "isFolder": bool(row.get("is_folder")),
            "sortOrder": int(row.get("sort_order") or 0),
            "createdBy": row.get("created_by"),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _row_to_environment(self, row: dict[str, Any]) -> dict[str, Any]:
        variables = self._parse_json_dict(row.get("variables_json"), default={})
        normalized_variables = {str(k): str(v) for k, v in variables.items()}
        return {
            "id": row["id"],
            "collectionId": row["collection_id"],
            "name": row["name"],
            "variables": normalized_variables,
            "isDefault": bool(row.get("is_default")),
            "createdBy": row.get("created_by"),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _row_to_run(self, row: dict[str, Any]) -> dict[str, Any]:
        meta = self._parse_json_dict(row.get("meta_json"), default={})
        extracted = meta.get("extractedVariables", {}) if isinstance(meta, dict) else {}
        extracted_variables = (
            {str(k): str(v) for k, v in extracted.items()}
            if isinstance(extracted, dict)
            else {}
        )
        return {
            "id": row["id"],
            "requestId": row["request_id"],
            "collectionId": row["collection_id"],
            "method": str(row.get("method", "GET")).upper(),
            "url": row.get("url") or "",
            "statusCode": row.get("status_code"),
            "durationMs": int(row.get("duration_ms") or 0),
            "success": bool(row.get("success")),
            "responseHeaders": self._parse_json_dict(row.get("response_headers_json"), default={}),
            "responseBody": row.get("response_body") or "",
            "responseSize": int(row.get("response_size") or 0),
            "errorMessage": row.get("error_message"),
            "assertions": self._parse_json_list(row.get("assertions_json"), default=[]),
            "extractedVariables": extracted_variables,
            "createdBy": row.get("created_by"),
            "createdAt": row["created_at"],
        }

    @staticmethod
    def _parse_json_list(raw: Any, default: list[Any]) -> list[Any]:
        if isinstance(raw, str) and raw.strip():
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, list):
                    return decoded
            except json.JSONDecodeError:
                return default
        if isinstance(raw, list):
            return raw
        return default

    @staticmethod
    def _parse_json_dict(raw: Any, default: dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw, str) and raw.strip():
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, dict):
                    return decoded
            except json.JSONDecodeError:
                return default
        if isinstance(raw, dict):
            return raw
        return default

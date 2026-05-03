from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import time
from datetime import datetime
from typing import Awaitable, Callable, Optional
from urllib.parse import urljoin, urlparse

from app.models import (
    ApiKeyValue,
    SecurityScanRequest,
    SecurityScanResult,
    Vulnerability,
    VulnerabilitySeverity,
    ApiRequestPublic,
    ApiEnvironmentPublic,
)
from app.services.api_testing import ApiTestingService
from app.models import new_id, utc_now

class SecurityTestingService:
    def __init__(self, api_testing_service: ApiTestingService):
        self._api_service = api_testing_service
        self._tasks: dict[str, dict] = {}
        self._task_lock = asyncio.Lock()
        
        # 敏感信息识别正则 (PII)
        self.PII_PATTERNS = {
            "PHONE": r"1[3-9]\d{9}",
            "EMAIL": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            "ID_CARD": r"\d{17}[\dXx]",
            "SECRET_KEY": r"(?i)(key|secret|password|passwd|pwd|token)[\s:=]+['\"]?([a-zA-Z0-9_\-\.]{10,})['\"]?",
        }

    async def run_security_scan(
        self,
        request: SecurityScanRequest,
        collection_requests: list[ApiRequestPublic],
        env: ApiEnvironmentPublic | None = None,
    ) -> SecurityScanResult:
        """
        全自动 API 安全审计引擎
        """
        return await self._run_security_scan_core(
            request=request,
            collection_requests=collection_requests,
            env=env,
        )

    @staticmethod
    def normalize_target_url(target_url: str) -> str:
        text = str(target_url or "").strip()
        if not text:
            raise ValueError("targetUrl 不能为空")
        parsed = urlparse(text)
        if parsed.scheme:
            if parsed.scheme not in {"http", "https"}:
                raise ValueError("targetUrl 仅支持 http/https")
        else:
            text = f"https://{text}"
            parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("targetUrl 仅支持 http/https")
        if not parsed.netloc:
            raise ValueError("targetUrl 缺少主机名")
        return text

    async def build_requests_from_target_url(
        self,
        target_url: str,
        *,
        max_discovered_urls: int = 8,
    ) -> list[ApiRequestPublic]:
        normalized = self.normalize_target_url(target_url)
        limit = max(1, min(int(max_discovered_urls or 8), 30))

        seed_url = normalized
        urls: list[str] = [seed_url]
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, verify=False) as client:
                response = await client.get(seed_url)
            final_url = str(response.url)
            if final_url:
                urls[0] = final_url
            content_type = str(response.headers.get("content-type") or "").lower()
            if "text/html" in content_type:
                root_url = urls[0]
                for raw in self._extract_links_from_html(response.text or ""):
                    resolved = urljoin(root_url, raw)
                    parsed = urlparse(resolved)
                    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                        continue
                    if not self._is_same_origin(root_url, resolved):
                        continue
                    if resolved not in urls:
                        urls.append(resolved)
                    if len(urls) >= limit:
                        break
        except Exception:
            # 探测站点无法访问时，仍返回用户输入 URL 作为最小扫描集。
            pass

        urls = urls[:limit]
        now = utc_now()
        return [
            ApiRequestPublic(
                id=f"urlscan_req_{index}",
                collectionId="target_url",
                parentId=None,
                name=f"URL Scan Target {index}",
                groupName="url_scan",
                tags=["url-scan"],
                method="GET",
                url=item,
                query=[],
                headers=[],
                bodyMode="none",
                bodyRaw="",
                bodyForm=[],
                authType="none",
                auth={},
                tests=[],
                preScript="",
                testScript="",
                isFolder=False,
                sortOrder=index,
                createdBy=None,
                createdAt=now,
                updatedAt=now,
            )
            for index, item in enumerate(urls, start=1)
        ]

    @staticmethod
    def _extract_links_from_html(html: str) -> list[str]:
        text = str(html or "")
        matches = re.findall(r"""(?:href|src)\s*=\s*["']([^"'#]+)["']""", text, flags=re.IGNORECASE)
        return [str(item).strip() for item in matches if str(item).strip()]

    @staticmethod
    def _is_same_origin(base_url: str, candidate_url: str) -> bool:
        base = urlparse(base_url)
        candidate = urlparse(candidate_url)
        return (
            base.scheme.lower() == candidate.scheme.lower()
            and base.netloc.lower() == candidate.netloc.lower()
        )

    async def start_scan_task(
        self,
        *,
        request: SecurityScanRequest,
        collection_requests: list[ApiRequestPublic],
        env: ApiEnvironmentPublic | None = None,
        on_completed: Optional[Callable[[SecurityScanResult], Awaitable[SecurityScanResult]]] = None,
    ) -> dict:
        task_id = new_id("sect")
        now = utc_now()
        async with self._task_lock:
            self._tasks[task_id] = {
                "taskId": task_id,
                "status": "queued",
                "progressPct": 0,
                "processedRequests": 0,
                "totalRequests": len(collection_requests),
                "result": None,
                "error": None,
                "cancelRequested": False,
                "startedAt": now,
                "endedAt": None,
            }
        asyncio.create_task(
            self._run_scan_task(
                task_id=task_id,
                request=request,
                collection_requests=collection_requests,
                env=env,
                on_completed=on_completed,
            )
        )
        return await self.get_scan_task(task_id) or {"taskId": task_id, "status": "queued"}

    async def get_scan_task(self, task_id: str) -> dict | None:
        async with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return dict(task)

    async def cancel_scan_task(self, task_id: str) -> dict | None:
        async with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            if task["status"] in {"queued", "running"}:
                task["cancelRequested"] = True
            return dict(task)

    async def _run_scan_task(
        self,
        *,
        task_id: str,
        request: SecurityScanRequest,
        collection_requests: list[ApiRequestPublic],
        env: ApiEnvironmentPublic | None,
        on_completed: Optional[Callable[[SecurityScanResult], Awaitable[SecurityScanResult]]],
    ) -> None:
        async with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["status"] = "running"

        async def _progress(processed: int, total: int) -> None:
            pct = int((processed / total) * 100) if total > 0 else 100
            async with self._task_lock:
                item = self._tasks.get(task_id)
                if not item:
                    return
                item["processedRequests"] = processed
                item["totalRequests"] = total
                item["progressPct"] = max(0, min(pct, 100))

        async def _should_cancel() -> bool:
            async with self._task_lock:
                item = self._tasks.get(task_id)
                if not item:
                    return True
                return bool(item.get("cancelRequested"))

        try:
            result = await self._run_security_scan_core(
                request=request,
                collection_requests=collection_requests,
                env=env,
                progress_hook=_progress,
                cancel_check=_should_cancel,
            )
            if on_completed is not None:
                result = await on_completed(result)
            async with self._task_lock:
                item = self._tasks.get(task_id)
                if not item:
                    return
                item["status"] = "completed"
                item["progressPct"] = 100
                item["processedRequests"] = item.get("totalRequests", 0)
                item["result"] = result.model_dump(mode="json")
                item["endedAt"] = utc_now()
        except asyncio.CancelledError:
            async with self._task_lock:
                item = self._tasks.get(task_id)
                if not item:
                    return
                item["status"] = "cancelled"
                item["endedAt"] = utc_now()
                item["error"] = "扫描任务已取消"
        except Exception as exc:
            async with self._task_lock:
                item = self._tasks.get(task_id)
                if not item:
                    return
                item["status"] = "failed"
                item["endedAt"] = utc_now()
                item["error"] = str(exc)

    async def _run_security_scan_core(
        self,
        *,
        request: SecurityScanRequest,
        collection_requests: list[ApiRequestPublic],
        env: ApiEnvironmentPublic | None,
        progress_hook: Optional[Callable[[int, int], Awaitable[None]]] = None,
        cancel_check: Optional[Callable[[], Awaitable[bool]]] = None,
    ) -> SecurityScanResult:
        scan_id = f"sec-{int(time.time())}"
        start_time = datetime.now()
        vulnerabilities = []
        total = len(collection_requests)

        for idx, req_meta in enumerate(collection_requests, start=1):
            if cancel_check is not None and await cancel_check():
                raise asyncio.CancelledError()
            # 1. 敏感信息泄露扫描 (PII Scan)
            if "pii_scan" in request.scanTypes:
                pii_vulns = await self._scan_pii(req_meta, env)
                vulnerabilities.extend(pii_vulns)
            # 2. 注入漏洞扫描 (SQLi Simulation)
            if "owasp_api" in request.scanTypes:
                sqli_vulns = await self._scan_injection(req_meta, env)
                vulnerabilities.extend(sqli_vulns)
            # 3. 未授权访问扫描 (Auth Bypass)
            if "auth_bypass" in request.scanTypes:
                auth_vulns = await self._scan_auth_bypass(req_meta, env)
                vulnerabilities.extend(auth_vulns)
            # 4. 安全响应头检查
            if "security_headers" in request.scanTypes:
                header_vulns = await self._scan_security_headers(req_meta, env)
                vulnerabilities.extend(header_vulns)
            # 5. CORS 配置检查
            if "cors_misconfig" in request.scanTypes:
                cors_vulns = await self._scan_cors_misconfig(req_meta, env)
                vulnerabilities.extend(cors_vulns)
            # 6. 反射型 XSS 检查
            if "xss_reflection" in request.scanTypes:
                xss_vulns = await self._scan_xss_reflection(req_meta, env)
                vulnerabilities.extend(xss_vulns)
            # 7. 错误信息泄露检查
            if "error_leak" in request.scanTypes:
                err_vulns = await self._scan_error_information_leak(req_meta, env)
                vulnerabilities.extend(err_vulns)
            # 8. 明文传输检查
            if "insecure_transport" in request.scanTypes:
                transport_vulns = self._scan_insecure_transport(req_meta)
                vulnerabilities.extend(transport_vulns)
            # 9. IDOR 枚举探测
            if "idor_enumeration" in request.scanTypes:
                idor_vulns = await self._scan_idor_enumeration(req_meta, env)
                vulnerabilities.extend(idor_vulns)
            # 10. 路径穿越探测
            if "path_traversal" in request.scanTypes:
                traversal_vulns = await self._scan_path_traversal(req_meta, env)
                vulnerabilities.extend(traversal_vulns)
            # 11. SSRF 探测
            if "ssrf_probe" in request.scanTypes:
                ssrf_vulns = await self._scan_ssrf_probe(req_meta, env)
                vulnerabilities.extend(ssrf_vulns)
            # 12. 文件上传安全探测
            if "file_upload_security" in request.scanTypes:
                upload_vulns = await self._scan_file_upload_security(req_meta, env)
                vulnerabilities.extend(upload_vulns)
            # 13. 命令/模板注入探测
            if "command_template_injection" in request.scanTypes:
                cti_vulns = await self._scan_command_template_injection(req_meta, env)
                vulnerabilities.extend(cti_vulns)
            # 14. JWT / 会话安全探测
            if "jwt_session_security" in request.scanTypes:
                jwt_vulns = await self._scan_jwt_session_security(req_meta, env)
                vulnerabilities.extend(jwt_vulns)
            # 15. 限流与防爆破探测
            if "rate_limit_bruteforce" in request.scanTypes:
                rl_vulns = await self._scan_rate_limit_bruteforce(req_meta, env)
                vulnerabilities.extend(rl_vulns)
            if progress_hook is not None:
                await progress_hook(idx, total)

        vulnerabilities = self._deduplicate_vulnerabilities(vulnerabilities)
        crit = len([v for v in vulnerabilities if v.severity == VulnerabilitySeverity.CRITICAL])
        high = len([v for v in vulnerabilities if v.severity == VulnerabilitySeverity.HIGH])
        med = len([v for v in vulnerabilities if v.severity == VulnerabilitySeverity.MEDIUM])
        low = len([v for v in vulnerabilities if v.severity == VulnerabilitySeverity.LOW])
        return SecurityScanResult(
            scanId=scan_id,
            status="completed",
            totalIssues=len(vulnerabilities),
            criticalCount=crit,
            highCount=high,
            mediumCount=med,
            lowCount=low,
            vulnerabilities=vulnerabilities,
            startTime=start_time,
            endTime=datetime.now(),
        )

    @staticmethod
    def _deduplicate_vulnerabilities(items: list[Vulnerability]) -> list[Vulnerability]:
        deduped: list[Vulnerability] = []
        seen: set[str] = set()
        for item in items:
            signature = "|".join(
                [
                    str(item.type or "").strip().lower(),
                    str(item.severity or "").strip().lower(),
                    str(item.method or "").strip().upper(),
                    str(item.endpoint or "").strip(),
                    str(item.description or "").strip(),
                ]
            )
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(item)
        return deduped

    async def _scan_pii(self, req: ApiRequestPublic, env: ApiEnvironmentPublic | None) -> list[Vulnerability]:
        """扫描响应中是否有敏感明文数据"""
        vulns = []
        try:
            # 执行原始请求
            res = await self._api_service.run_request(request=req, environment=env)
            body = res.body_text or ""
            
            for p_type, pattern in self.PII_PATTERNS.items():
                matches = re.findall(pattern, body)
                if matches:
                    first_match = matches[0]
                    if isinstance(first_match, tuple):
                        first_text = "".join(str(item) for item in first_match if item)
                    else:
                        first_text = str(first_match)
                    first_text = first_text[:80]
                    vulns.append(Vulnerability(
                        type="Sensitive Data Exposure",
                        severity=VulnerabilitySeverity.HIGH if p_type != "SECRET_KEY" else VulnerabilitySeverity.CRITICAL,
                        endpoint=req.url,
                        method=req.method,
                        description=f"检测到响应中包含未脱敏的 {p_type} 信息。",
                        evidence=f"matched={first_text} (count={len(matches)})",
                        remediation="在响应返回给前端前，请使用掩码（如 138****0000）或在此敏感字段上执行脱敏逻辑。"
                    ))
        except Exception:
            pass
        return vulns

    async def _scan_security_headers(self, req: ApiRequestPublic, env: ApiEnvironmentPublic | None) -> list[Vulnerability]:
        vulns: list[Vulnerability] = []
        try:
            res = await self._api_service.run_request(request=req, environment=env)
            headers = {str(k).lower(): str(v) for k, v in (res.responseHeaders or {}).items()}
            missing: list[str] = []
            required_headers = {
                "strict-transport-security": "建议开启 HSTS，防止协议降级攻击",
                "content-security-policy": "建议设置 CSP，降低 XSS 风险",
                "x-frame-options": "建议设置 X-Frame-Options，降低点击劫持风险",
                "x-content-type-options": "建议设置 X-Content-Type-Options: nosniff",
                "referrer-policy": "建议设置 Referrer-Policy，控制来源泄露",
            }
            for header_key in required_headers:
                if header_key not in headers:
                    missing.append(header_key)
            if missing:
                vulns.append(
                    Vulnerability(
                        type="Missing Security Headers",
                        severity=VulnerabilitySeverity.MEDIUM,
                        endpoint=req.url,
                        method=req.method,
                        description="响应缺少关键安全头，可能增加浏览器侧攻击风险。",
                        evidence=f"missing={', '.join(missing)}",
                        remediation="补齐 HSTS/CSP/X-Frame-Options/X-Content-Type-Options/Referrer-Policy 等关键响应头。",
                    )
                )
        except Exception:
            pass
        return vulns

    async def _scan_cors_misconfig(self, req: ApiRequestPublic, env: ApiEnvironmentPublic | None) -> list[Vulnerability]:
        vulns: list[Vulnerability] = []
        req_mutated = req.model_copy(deep=True)
        probe_origin = "https://evil.example"
        has_origin = False
        for item in req_mutated.headers:
            if item.key.lower() == "origin":
                item.value = probe_origin
                has_origin = True
                break
        if not has_origin:
            req_mutated.headers.append(ApiKeyValue(key="Origin", value=probe_origin, enabled=True, description=""))
        try:
            res = await self._api_service.run_request(request=req_mutated, environment=env)
            headers = {str(k).lower(): str(v) for k, v in (res.responseHeaders or {}).items()}
            acao = headers.get("access-control-allow-origin", "")
            acc = headers.get("access-control-allow-credentials", "").lower()
            if acao == "*" or (acao == probe_origin and acc == "true"):
                vulns.append(
                    Vulnerability(
                        type="CORS Misconfiguration",
                        severity=VulnerabilitySeverity.HIGH,
                        endpoint=req.url,
                        method=req.method,
                        description="跨域策略可能过宽，存在跨站读取风险。",
                        evidence=f"acao={acao}, acc={acc}",
                        remediation="限制 Access-Control-Allow-Origin 为可信域名，且避免与 Allow-Credentials=true 组合开放。",
                    )
                )
        except Exception:
            pass
        return vulns

    async def _scan_xss_reflection(self, req: ApiRequestPublic, env: ApiEnvironmentPublic | None) -> list[Vulnerability]:
        vulns: list[Vulnerability] = []
        payload = "<script>alert('xss')</script>"
        req_mutated = req.model_copy(deep=True)
        injected = False
        for item in req_mutated.query:
            if item.enabled:
                item.value = payload
                injected = True
                break
        if not injected:
            req_mutated.query.append(ApiKeyValue(key="xss_probe", value=payload, enabled=True, description=""))
            injected = True
        if not injected:
            return vulns
        try:
            res = await self._api_service.run_request(request=req_mutated, environment=env)
            body = (res.body_text or "").lower()
            if payload.lower() in body:
                vulns.append(
                    Vulnerability(
                        type="Potential Reflected XSS",
                        severity=VulnerabilitySeverity.HIGH,
                        endpoint=req.url,
                        method=req.method,
                        description="响应中反射了未编码的输入内容，可能存在反射型 XSS。",
                        evidence="payload reflected in response body",
                        remediation="对所有可回显输入进行 HTML 实体编码，并在前端渲染前做输出转义。",
                    )
                )
        except Exception:
            pass
        return vulns

    async def _scan_error_information_leak(self, req: ApiRequestPublic, env: ApiEnvironmentPublic | None) -> list[Vulnerability]:
        vulns: list[Vulnerability] = []
        req_mutated = req.model_copy(deep=True)
        req_mutated.query.append(ApiKeyValue(key="__error_probe", value="'\"\\", enabled=True, description=""))
        markers = [
            "traceback",
            "exception",
            "stack trace",
            "sql syntax",
            "nullpointerexception",
            "syntax error",
            "internal server error",
        ]
        try:
            res = await self._api_service.run_request(request=req_mutated, environment=env)
            body = (res.body_text or "").lower()
            status = int(res.status_code or 0)
            if status >= 500 and any(marker in body for marker in markers):
                vulns.append(
                    Vulnerability(
                        type="Verbose Error Information Leak",
                        severity=VulnerabilitySeverity.MEDIUM,
                        endpoint=req.url,
                        method=req.method,
                        description="错误响应可能泄露内部实现细节（堆栈、数据库或框架信息）。",
                        evidence=f"status={status}, matched error marker",
                        remediation="生产环境关闭详细错误输出，统一返回通用错误码并将细节记录到服务端日志。",
                    )
                )
        except Exception:
            pass
        return vulns

    def _scan_insecure_transport(self, req: ApiRequestPublic) -> list[Vulnerability]:
        vulns: list[Vulnerability] = []
        scheme = (urlparse(req.url).scheme or "").lower()
        host = (urlparse(req.url).hostname or "").lower()
        if scheme == "http" and host not in {"localhost", "127.0.0.1"}:
            vulns.append(
                Vulnerability(
                    type="Insecure Transport (HTTP)",
                    severity=VulnerabilitySeverity.MEDIUM,
                    endpoint=req.url,
                    method=req.method,
                    description="接口使用明文 HTTP 传输，可能遭受中间人攻击或窃听。",
                    evidence=f"url={req.url}",
                    remediation="生产环境统一使用 HTTPS，并启用 HSTS 强制加密传输。",
                )
            )
        return vulns

    async def _scan_injection(self, req: ApiRequestPublic, env: ApiEnvironmentPublic | None) -> list[Vulnerability]:
        """基础 SQL 注入尝试（对请求参数做轻量变异并验证响应特征）"""
        vulns = []
        if req.method not in ["GET", "POST", "PUT", "PATCH"]:
            return vulns

        payloads = ["' OR '1'='1", "\" OR \"1\"=\"1"]
        sql_error_markers = [
            "sql syntax",
            "mysql",
            "postgresql",
            "sqlite",
            "sqlstate",
            "odbc",
            "unclosed quotation mark",
            "you have an error in your sql syntax",
        ]
        base_has_query = any(item.enabled for item in req.query)
        base_has_form = any(item.enabled for item in req.bodyForm)
        base_has_raw = bool((req.bodyRaw or "").strip())
        if not (base_has_query or base_has_form or base_has_raw):
            return vulns

        for payload in payloads:
            req_mutated = req.model_copy(deep=True)
            mutated = False
            for item in req_mutated.query:
                if item.enabled:
                    item.value = f"{item.value}{payload}"
                    mutated = True
                    break
            if not mutated and req_mutated.bodyMode == "form":
                for item in req_mutated.bodyForm:
                    if item.enabled:
                        item.value = f"{item.value}{payload}"
                        mutated = True
                        break
            if not mutated and req_mutated.bodyMode in {"raw", "json"}:
                req_mutated.bodyRaw = f"{req_mutated.bodyRaw}{payload}"
                mutated = True
            if not mutated:
                continue
            try:
                res = await self._api_service.run_request(request=req_mutated, environment=env)
                body_lower = (res.body_text or "").lower()
                status_code = res.status_code or 0
                if status_code >= 500 or any(marker in body_lower for marker in sql_error_markers):
                    vulns.append(Vulnerability(
                        type="Potential SQL Injection",
                        severity=VulnerabilitySeverity.CRITICAL,
                        endpoint=req.url,
                        method=req.method,
                        description="接口参数对特殊字符未进行充分过滤，可能存在 SQL 注入风险。",
                        evidence=f"payload={payload}, status={status_code}",
                        remediation="请使用参数化查询（Parameterized Queries）或 ORM，严禁将用户输入直接拼接在 SQL 语句中。"
                    ))
                    break
            except Exception:
                continue
        return vulns

    async def _scan_auth_bypass(self, req: ApiRequestPublic, env: ApiEnvironmentPublic | None) -> list[Vulnerability]:
        """未授权访问扫描"""
        vulns = []
        # 尝试剔除 Authorization Header
        has_auth = any(h.key.lower() == "authorization" for h in req.headers)
        if has_auth:
            headers_no_auth = [h for h in req.headers if h.key.lower() != "authorization"]
            req_no_auth = req.model_copy(update={"headers": headers_no_auth})
            
            try:
                res = await self._api_service.run_request(request=req_no_auth, environment=env)
                if res.status_code and 200 <= res.status_code < 300:
                    vulns.append(Vulnerability(
                        type="Broken Object Level Authorization",
                        severity=VulnerabilitySeverity.CRITICAL,
                        endpoint=req.url,
                        method=req.method,
                        description="接口在缺失鉴权凭证的情况下依然返回了 200 成功状态码，存在严重的安全准入风险。",
                        evidence="Status 200 with no valid Authentication header.",
                        remediation="请在服务端增加身份校验拦截器，对所有受保护的端点强制执行 Token 校验。"
                    ))
            except Exception:
                pass
        return vulns

    async def _scan_idor_enumeration(self, req: ApiRequestPublic, env: ApiEnvironmentPublic | None) -> list[Vulnerability]:
        """IDOR 探测：尝试修改请求中的对象 ID 并观察是否仍返回成功。"""
        vulns: list[Vulnerability] = []
        id_pattern = re.compile(r"\b\d{1,12}\b")

        req_mutated = req.model_copy(deep=True)
        mutated = False

        def _bump_numeric(text: str) -> str:
            def _repl(match: re.Match[str]) -> str:
                try:
                    current = int(match.group(0))
                    return str(current + 1)
                except Exception:
                    return match.group(0)
            return id_pattern.sub(_repl, text, count=1)

        new_url = _bump_numeric(req_mutated.url)
        if new_url != req_mutated.url:
            req_mutated.url = new_url
            mutated = True

        for item in req_mutated.query:
            if item.enabled and id_pattern.search(item.value or ""):
                item.value = _bump_numeric(item.value or "")
                mutated = True
                break

        if not mutated and req_mutated.bodyMode == "form":
            for item in req_mutated.bodyForm:
                if item.enabled and id_pattern.search(item.value or ""):
                    item.value = _bump_numeric(item.value or "")
                    mutated = True
                    break

        if not mutated and req_mutated.bodyMode in {"raw", "json"}:
            raw = req_mutated.bodyRaw or ""
            replaced = _bump_numeric(raw)
            if replaced != raw:
                req_mutated.bodyRaw = replaced
                mutated = True

        if not mutated:
            return vulns

        try:
            res = await self._api_service.run_request(request=req_mutated, environment=env)
            status = int(res.status_code or 0)
            body_lower = (res.body_text or "").lower()
            sensitive_markers = ["email", "phone", "id", "name", "order", "account", "user"]
            if 200 <= status < 300 and any(marker in body_lower for marker in sensitive_markers):
                vulns.append(
                    Vulnerability(
                        type="Potential IDOR (Object Enumeration)",
                        severity=VulnerabilitySeverity.HIGH,
                        endpoint=req.url,
                        method=req.method,
                        description="修改对象 ID 后仍可成功访问资源，疑似缺少对象级授权校验。",
                        evidence=f"mutated-request status={status}",
                        remediation="在服务端对每个资源对象执行 owner/tenant/ACL 校验，不要仅依赖前端传参或 URL 结构。",
                    )
                )
        except Exception:
            pass
        return vulns

    async def _scan_path_traversal(self, req: ApiRequestPublic, env: ApiEnvironmentPublic | None) -> list[Vulnerability]:
        """路径穿越探测：注入目录穿越载荷，检查是否出现文件读取特征。"""
        vulns: list[Vulnerability] = []
        payloads = ["../../../../etc/passwd", "..\\..\\..\\..\\windows\\win.ini", "/etc/passwd"]
        body_markers = ["root:x:", "[extensions]", "[fonts]", "for 16-bit app support"]

        for payload in payloads:
            req_mutated = req.model_copy(deep=True)
            mutated = False
            for item in req_mutated.query:
                if item.enabled:
                    item.value = payload
                    mutated = True
                    break
            if not mutated and req_mutated.bodyMode == "form":
                for item in req_mutated.bodyForm:
                    if item.enabled:
                        item.value = payload
                        mutated = True
                        break
            if not mutated and req_mutated.bodyMode in {"raw", "json"}:
                raw = req_mutated.bodyRaw or ""
                req_mutated.bodyRaw = f"{raw}{payload}"
                mutated = True
            if not mutated:
                req_mutated.query.append(ApiKeyValue(key="file", value=payload, enabled=True, description=""))
                mutated = True
            try:
                res = await self._api_service.run_request(request=req_mutated, environment=env)
                status = int(res.status_code or 0)
                body_lower = (res.body_text or "").lower()
                if status == 200 and any(marker in body_lower for marker in body_markers):
                    vulns.append(
                        Vulnerability(
                            type="Potential Path Traversal",
                            severity=VulnerabilitySeverity.HIGH,
                            endpoint=req.url,
                            method=req.method,
                            description="目录穿越载荷可能导致读取系统文件，存在路径穿越风险。",
                            evidence=f"payload={payload}, status={status}",
                            remediation="对文件路径参数执行白名单校验与规范化，拒绝包含 ../、..\\ 等路径跳转片段。",
                        )
                    )
                    break
            except Exception:
                continue
        return vulns

    async def _scan_ssrf_probe(self, req: ApiRequestPublic, env: ApiEnvironmentPublic | None) -> list[Vulnerability]:
        """SSRF 探测：向 URL 型参数注入内网地址并观察异常访问特征。"""
        vulns: list[Vulnerability] = []
        payloads = [
            "http://127.0.0.1:80",
            "http://169.254.169.254/latest/meta-data/",
            "http://localhost:8080",
        ]
        url_like_pattern = re.compile(r"(url|uri|endpoint|callback|redirect|webhook|target|host)", re.IGNORECASE)
        marker_pattern = re.compile(r"(127\.0\.0\.1|localhost|169\.254\.169\.254|connection refused|timed out|dial tcp)", re.IGNORECASE)

        for payload in payloads:
            req_mutated = req.model_copy(deep=True)
            mutated = False

            for item in req_mutated.query:
                if item.enabled and (url_like_pattern.search(item.key or "") or item.value.startswith("http")):
                    item.value = payload
                    mutated = True
                    break
            if not mutated and req_mutated.bodyMode == "form":
                for item in req_mutated.bodyForm:
                    if item.enabled and (url_like_pattern.search(item.key or "") or item.value.startswith("http")):
                        item.value = payload
                        mutated = True
                        break
            if not mutated and req_mutated.bodyMode in {"raw", "json"}:
                raw = req_mutated.bodyRaw or ""
                replaced = raw
                try:
                    if req_mutated.bodyMode == "json":
                        parsed = json.loads(raw) if raw.strip() else {}
                        if isinstance(parsed, dict):
                            for key, value in parsed.items():
                                if isinstance(value, str) and (url_like_pattern.search(str(key)) or value.startswith("http")):
                                    parsed[key] = payload
                                    mutated = True
                                    break
                            if mutated:
                                replaced = json.dumps(parsed, ensure_ascii=False)
                    if not mutated and raw:
                        replaced = re.sub(r"https?://[^\s\"']+", payload, raw, count=1)
                        if replaced != raw:
                            mutated = True
                except Exception:
                    replaced = re.sub(r"https?://[^\s\"']+", payload, raw, count=1)
                    if replaced != raw:
                        mutated = True
                if mutated:
                    req_mutated.bodyRaw = replaced

            if not mutated:
                req_mutated.query.append(ApiKeyValue(key="url", value=payload, enabled=True, description=""))
                mutated = True

            try:
                res = await self._api_service.run_request(request=req_mutated, environment=env)
                status = int(res.status_code or 0)
                body = res.body_text or ""
                if status >= 500 and marker_pattern.search(body):
                    vulns.append(
                        Vulnerability(
                            type="Potential SSRF",
                            severity=VulnerabilitySeverity.HIGH,
                            endpoint=req.url,
                            method=req.method,
                            description="接口可能可被利用访问内网或云元数据地址，存在 SSRF 风险。",
                            evidence=f"payload={payload}, status={status}",
                            remediation="禁止访问内网/IP 字面量地址，增加目标域名白名单与 DNS/IP 解析二次校验。",
                        )
                    )
                    break
            except Exception:
                continue
        return vulns

    async def _scan_file_upload_security(self, req: ApiRequestPublic, env: ApiEnvironmentPublic | None) -> list[Vulnerability]:
        """文件上传安全探测：后缀绕过、MIME 欺骗、可执行内容探针。"""
        vulns: list[Vulnerability] = []
        if str(req.method).upper() not in {"POST", "PUT", "PATCH"}:
            return vulns

        upload_key_pattern = re.compile(r"(file|upload|attachment|image|avatar|document)", re.IGNORECASE)
        has_upload_hint = (
            upload_key_pattern.search(req.url or "") is not None
            or any(upload_key_pattern.search(item.key or "") for item in req.query)
            or any(upload_key_pattern.search(item.key or "") for item in req.bodyForm)
            or "multipart/form-data" in " ".join((h.value or "").lower() for h in req.headers if h.enabled)
        )
        if not has_upload_hint:
            return vulns

        probes = [
            {"filename": "shell.php.jpg", "mime": "image/jpeg", "content": "<?php echo 'pwn'; ?>"},
            {"filename": "evil.jsp;.png", "mime": "image/png", "content": "<% out.print(1); %>"},
            {"filename": "malicious.svg", "mime": "image/svg+xml", "content": "<svg><script>alert(1)</script></svg>"},
        ]

        for probe in probes:
            req_mutated = req.model_copy(deep=True)
            req_mutated.bodyMode = "form"
            req_mutated.bodyForm = [
                ApiKeyValue(key="filename", value=str(probe["filename"]), enabled=True, description=""),
                ApiKeyValue(key="contentType", value=str(probe["mime"]), enabled=True, description=""),
                ApiKeyValue(key="fileContent", value=str(probe["content"]), enabled=True, description=""),
            ]
            replaced_ct = False
            for header in req_mutated.headers:
                if header.enabled and header.key.lower() == "content-type":
                    header.value = "multipart/form-data"
                    replaced_ct = True
            if not replaced_ct:
                req_mutated.headers.append(ApiKeyValue(key="Content-Type", value="multipart/form-data", enabled=True, description=""))
            try:
                res = await self._api_service.run_request(request=req_mutated, environment=env)
                status = int(res.status_code or 0)
                body = (res.body_text or "").lower()
                accepted_markers = ["upload success", "uploaded", "ok", "success", "saved"]
                if 200 <= status < 300 and any(marker in body for marker in accepted_markers):
                    vulns.append(
                        Vulnerability(
                            type="Potential Unsafe File Upload",
                            severity=VulnerabilitySeverity.HIGH,
                            endpoint=req.url,
                            method=req.method,
                            description="上传接口可能接受了危险后缀或 MIME 欺骗内容。",
                            evidence=f"filename={probe['filename']}, mime={probe['mime']}, status={status}",
                            remediation="对扩展名与 MIME 做双重白名单校验，进行魔数检测，上传文件落盘前做内容安全扫描。",
                        )
                    )
                    break
            except Exception:
                continue
        return vulns

    async def _scan_command_template_injection(self, req: ApiRequestPublic, env: ApiEnvironmentPublic | None) -> list[Vulnerability]:
        """命令注入 / SSTI 轻量探测。"""
        vulns: list[Vulnerability] = []
        payloads = [
            ("cmd", "cmd_probe", ";cat /etc/passwd"),
            ("cmd", "cmd_probe", "| whoami"),
            ("ssti", "tpl_probe", "{{7*7}}"),
            ("ssti", "tpl_probe", "${7*7}"),
        ]
        markers = ["root:x:", "bin/bash", "uid=", "gid=", "49"]

        for category, key, payload in payloads:
            req_mutated = req.model_copy(deep=True)
            mutated = False
            for item in req_mutated.query:
                if item.enabled:
                    item.value = f"{item.value}{payload}"
                    mutated = True
                    break
            if not mutated and req_mutated.bodyMode == "form":
                for item in req_mutated.bodyForm:
                    if item.enabled:
                        item.value = f"{item.value}{payload}"
                        mutated = True
                        break
            if not mutated and req_mutated.bodyMode in {"raw", "json"}:
                req_mutated.bodyRaw = f"{req_mutated.bodyRaw}{payload}"
                mutated = True
            if not mutated:
                req_mutated.query.append(ApiKeyValue(key=key, value=payload, enabled=True, description=""))
            try:
                res = await self._api_service.run_request(request=req_mutated, environment=env)
                status = int(res.status_code or 0)
                body = (res.body_text or "").lower()
                if status >= 500 or any(marker in body for marker in markers):
                    vuln_type = "Potential Command Injection" if category == "cmd" else "Potential Template Injection"
                    vulns.append(
                        Vulnerability(
                            type=vuln_type,
                            severity=VulnerabilitySeverity.HIGH,
                            endpoint=req.url,
                            method=req.method,
                            description="接口输入可能被解释执行，存在命令注入或模板注入风险。",
                            evidence=f"payload={payload}, status={status}",
                            remediation="禁止拼接执行系统命令；模板渲染使用沙箱和严格变量白名单，关闭表达式执行能力。",
                        )
                    )
                    break
            except Exception:
                continue
        return vulns

    async def _scan_jwt_session_security(self, req: ApiRequestPublic, env: ApiEnvironmentPublic | None) -> list[Vulnerability]:
        """JWT / 会话安全探测：无 exp、过期时间过长、签名篡改容忍。"""
        vulns: list[Vulnerability] = []
        bearer = ""
        for header in req.headers:
            if header.enabled and header.key.lower() == "authorization" and header.value.lower().startswith("bearer "):
                bearer = header.value[7:].strip()
                break
        if not bearer:
            return vulns

        header_claims, payload_claims = self._decode_jwt_claims(bearer)
        alg = str(header_claims.get("alg") or "").lower() if isinstance(header_claims, dict) else ""
        exp_value = payload_claims.get("exp") if isinstance(payload_claims, dict) else None
        iat_value = payload_claims.get("iat") if isinstance(payload_claims, dict) else None

        if alg == "none":
            vulns.append(
                Vulnerability(
                    type="Insecure JWT Algorithm",
                    severity=VulnerabilitySeverity.CRITICAL,
                    endpoint=req.url,
                    method=req.method,
                    description="JWT 使用了 alg=none，存在签名绕过风险。",
                    evidence="jwt.header.alg=none",
                    remediation="服务端禁用 none 算法，并强制使用受信任的签名算法（如 RS256/ES256）。",
                )
            )

        if exp_value is None:
            vulns.append(
                Vulnerability(
                    type="JWT Without Expiration",
                    severity=VulnerabilitySeverity.HIGH,
                    endpoint=req.url,
                    method=req.method,
                    description="JWT 未包含 exp 过期时间，令牌生命周期不可控。",
                    evidence="jwt.payload.exp missing",
                    remediation="为访问令牌设置较短过期时间，并配合刷新令牌机制。",
                )
            )
        else:
            try:
                exp_int = int(exp_value)
                iat_int = int(iat_value) if iat_value is not None else exp_int
                if exp_int - iat_int > 60 * 60 * 24 * 30:
                    vulns.append(
                        Vulnerability(
                            type="Overlong JWT Lifetime",
                            severity=VulnerabilitySeverity.MEDIUM,
                            endpoint=req.url,
                            method=req.method,
                            description="JWT 生命周期过长，令牌泄露后的风险窗口偏大。",
                            evidence=f"exp-iat={exp_int - iat_int}s",
                            remediation="将访问令牌有效期控制在分钟级或小时级，并启用短周期轮换与撤销策略。",
                        )
                    )
            except Exception:
                pass

        tampered = self._tamper_jwt_signature(bearer)
        if tampered:
            req_mutated = req.model_copy(deep=True)
            for header in req_mutated.headers:
                if header.enabled and header.key.lower() == "authorization":
                    header.value = f"Bearer {tampered}"
            try:
                res = await self._api_service.run_request(request=req_mutated, environment=env)
                status = int(res.status_code or 0)
                if 200 <= status < 300:
                    vulns.append(
                        Vulnerability(
                            type="JWT Signature Validation Bypass",
                            severity=VulnerabilitySeverity.CRITICAL,
                            endpoint=req.url,
                            method=req.method,
                            description="篡改 JWT 签名后请求仍成功，服务端可能未正确校验签名。",
                            evidence=f"tampered-jwt status={status}",
                            remediation="在网关或服务端统一强制校验 JWT 签名、issuer、audience 与有效期。",
                        )
                    )
            except Exception:
                pass

        return vulns

    async def _scan_rate_limit_bruteforce(self, req: ApiRequestPublic, env: ApiEnvironmentPublic | None) -> list[Vulnerability]:
        """限流与防爆破探测：高频重复请求是否触发 429 或限流头。"""
        vulns: list[Vulnerability] = []
        url_text = (req.url or "").lower()
        probe_keywords = ("login", "signin", "sms", "otp", "code", "password", "token", "auth")
        if not any(key in url_text for key in probe_keywords):
            return vulns
        if str(req.method).upper() not in {"POST", "PUT", "PATCH"}:
            return vulns

        statuses: list[int] = []
        has_limit_headers = False
        for _ in range(6):
            try:
                res = await self._api_service.run_request(request=req, environment=env)
                status = int(res.status_code or 0)
                statuses.append(status)
                headers = {str(k).lower(): str(v) for k, v in (res.responseHeaders or {}).items()}
                if any(key in headers for key in {"x-ratelimit-limit", "x-ratelimit-remaining", "retry-after"}):
                    has_limit_headers = True
            except Exception:
                continue

        if len(statuses) < 4:
            return vulns
        if 429 not in statuses and not has_limit_headers:
            vulns.append(
                Vulnerability(
                    type="Missing Rate Limiting / Brute-force Protection",
                    severity=VulnerabilitySeverity.HIGH,
                    endpoint=req.url,
                    method=req.method,
                    description="疑似认证/验证码接口在短时间重复请求下未触发限流。",
                    evidence=f"statuses={statuses}",
                    remediation="对登录、短信验证码、重置密码等接口启用频控、滑动窗口限流与账户/IP 联合防爆破策略。",
                )
            )
        return vulns

    @staticmethod
    def _decode_jwt_claims(token: str) -> tuple[dict, dict]:
        parts = token.split(".")
        if len(parts) < 2:
            return {}, {}

        def _decode_part(part: str) -> dict:
            padded = part + "=" * (-len(part) % 4)
            try:
                raw = base64.urlsafe_b64decode(padded.encode("utf-8"))
                payload = json.loads(raw.decode("utf-8", errors="ignore"))
                return payload if isinstance(payload, dict) else {}
            except (binascii.Error, ValueError, json.JSONDecodeError):
                return {}

        return _decode_part(parts[0]), _decode_part(parts[1])

    @staticmethod
    def _tamper_jwt_signature(token: str) -> str | None:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        return f"{parts[0]}.{parts[1]}.invalidsignature"

from __future__ import annotations

import json
import subprocess
import logging
import asyncio
import time
from pathlib import Path
from typing import Any

import httpx

from app.models import Artifact, TestCase, TestRun, utc_now
from app.repositories.run_repo import TestRunRepository

logger = logging.getLogger(__name__)

class AutomationService:
    def __init__(
        self,
        *,
        run_repo: TestRunRepository,
        artifacts_dir: Path,
        node_bin: str = "node",
        ui_runner_dir: Path,
        ui_runner_timeout_seconds: int = 180,
    ) -> None:
        self._repo = run_repo
        self._artifacts_dir = artifacts_dir
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._node_bin = node_bin
        self._ui_runner_dir = ui_runner_dir
        self._ui_runner_entry = self._ui_runner_dir / "src" / "index.js"
        self._ui_runner_timeout_seconds = max(int(ui_runner_timeout_seconds), 10)
        self._http_client = httpx.AsyncClient(
            follow_redirects=True,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            timeout=30.0,
        )

    async def aclose(self) -> None:
        await self._http_client.aclose()

    async def execute_run(self, run_id: str, test_case: TestCase) -> TestRun:
        run_data = self._repo.get_by_id(run_id)
        if not run_data:
            raise ValueError(f"Run {run_id} not found")
        
        run = TestRun.model_validate(run_data)
        
        self._repo.update(
            run.id,
            {
                "status": "running",
                "startedAt": utc_now(),
                "logs": run.logs + ["Accepted by automation service", f"runner={run.runnerType}"],
                "summary": "任务已进入自动化执行队列。",
            },
        )

        try:
            if run.runnerType == "api":
                result = await self._execute_api(run, test_case)
            elif run.runnerType == "ui":
                result = await self._execute_ui(run, test_case)
            else:
                result = {
                    "status": "failed",
                    "summary": f"Unsupported runner type: {run.runnerType}",
                    "logs": ["Unknown runner type"],
                    "artifacts": [],
                }
        except Exception as e:
            logger.exception(f"Execution failed for run {run.id}")
            result = {
                "status": "failed",
                "summary": f"执行出错: {str(e)}",
                "logs": [f"Error: {str(e)}"],
                "artifacts": [],
            }

        artifact_ids = []
        for art in result.get("artifacts", []):
            artifact_ids.append(art["id"])

        final_run_data = self._repo.update(
            run.id,
            {
                "status": result["status"],
                "finishedAt": utc_now(),
                "summary": result["summary"],
                "logs": run.logs + result["logs"],
                "artifactIds": artifact_ids,
            },
        )
        return TestRun.model_validate(final_run_data)

    async def _execute_api(self, run: TestRun, test_case: TestCase) -> dict[str, Any]:
        logger.info(f"_execute_api called for case {test_case.id}")
        logger.info(f"test_case.payload type: {type(test_case.payload)}")
        logger.info(f"test_case.payload value: {test_case.payload}")
        
        api_steps = test_case.payload.get("apiSteps", []) if test_case.payload else []
        logger.info(f"api_steps: {api_steps}, length: {len(api_steps)}")
        
        if not api_steps:
            return {
                "status": "failed",
                "summary": "测试用例没有 API 步骤",
                "logs": ["No API steps found in test case payload"],
                "artifacts": [],
            }

        report_path = self._artifacts_dir / f"{run.id}-api-report.json"
        logs = [f"开始执行 API 测试，共 {len(api_steps)} 个步骤"]
        step_results = []
        all_passed = True
        variables: dict[str, Any] = {}

        for idx, step in enumerate(api_steps):
            step_name = step.get("name", f"步骤 {idx + 1}")
            method = step.get("method", "GET")
            url = str(step.get("url", ""))
            
            logs.append(f"[步骤 {idx + 1}] {step_name}: {method} {url}")

            if not url:
                logs.append(f"[步骤 {idx + 1}] 跳过：URL 为空")
                step_results.append({
                    "step": idx + 1,
                    "name": step_name,
                    "status": "skipped",
                    "error": "URL 为空",
                })
                continue

            try:
                url = self._replace_variables(url, variables)
                headers = self._prepare_headers(step.get("headers", []), variables)
                body = self._prepare_body(step, variables)

                started = time.perf_counter()
                response = await self._http_client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=body if body and step.get("method") in ["POST", "PUT", "PATCH"] else None,
                    data=body if isinstance(body, str) else None,
                )
                duration_ms = int((time.perf_counter() - started) * 1000)

                step_passed = response.status_code < 400
                assertions = self._evaluate_tests(step.get("tests", []), response, duration_ms)
                if assertions:
                    step_passed = all(a.get("passed", False) for a in assertions)

                if not step_passed:
                    all_passed = False

                logs.append(f"[步骤 {idx + 1}] 完成: HTTP {response.status_code}, 耗时 {duration_ms}ms, {'通过' if step_passed else '失败'}")

                step_results.append({
                    "step": idx + 1,
                    "name": step_name,
                    "method": method,
                    "url": url,
                    "statusCode": response.status_code,
                    "durationMs": duration_ms,
                    "status": "passed" if step_passed else "failed",
                    "assertions": assertions,
                    "responseSize": len(response.content or b""),
                })

                try:
                    resp_json = response.json()
                    if isinstance(resp_json, dict):
                        variables.update({k: v for k, v in resp_json.items() if isinstance(v, (str, int, float, bool))})
                except Exception:
                    pass

            except Exception as e:
                all_passed = False
                logs.append(f"[步骤 {idx + 1}] 错误: {str(e)}")
                step_results.append({
                    "step": idx + 1,
                    "name": step_name,
                    "status": "error",
                    "error": str(e),
                })

        report = {
            "runId": run.id,
            "runner": "api",
            "caseTitle": test_case.title,
            "caseId": test_case.id,
            "status": "passed" if all_passed else "failed",
            "totalSteps": len(api_steps),
            "passedSteps": sum(1 for r in step_results if r.get("status") == "passed"),
            "failedSteps": sum(1 for r in step_results if r.get("status") in ["failed", "error"]),
            "steps": step_results,
            "executedAt": utc_now(),
        }

        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        art = {
            "id": f"art-{run.id}",
            "type": "json",
            "path": str(report_path),
            "label": "API 运行报告"
        }

        return {
            "status": report["status"],
            "summary": f"API 测试执行完成：{report['passedSteps']}/{report['totalSteps']} 步骤通过",
            "logs": logs,
            "artifacts": [art],
        }

    def _replace_variables(self, text: str, variables: dict[str, Any]) -> str:
        import re
        pattern = re.compile(r"{{\s*([a-zA-Z0-9_.-]+)\s*}}")
        def replacer(match: re.Match) -> str:
            key = match.group(1)
            return str(variables.get(key, match.group(0)))
        return pattern.sub(replacer, text)

    def _prepare_headers(self, headers: list, variables: dict[str, Any]) -> dict[str, str]:
        result = {}
        for h in headers:
            if isinstance(h, dict) and h.get("enabled", True):
                key = str(h.get("key", ""))
                value = str(h.get("value", ""))
                if key:
                    result[key] = self._replace_variables(value, variables)
        return result

    def _prepare_body(self, step: dict, variables: dict[str, Any]) -> Any:
        body_raw = step.get("body")
        if body_raw:
            if isinstance(body_raw, str):
                try:
                    return json.loads(self._replace_variables(body_raw, variables))
                except json.JSONDecodeError:
                    return self._replace_variables(body_raw, variables)
            return body_raw
        return None

    def _evaluate_tests(self, tests: list, response: httpx.Response, duration_ms: int) -> list[dict]:
        results = []
        json_payload: Any = None
        response_text = response.text
        for test in tests:
            if not isinstance(test, dict):
                continue
            test_type = test.get("type", "")
            target = test.get("target", "")
            operator = test.get("operator", "eq")
            expected = test.get("expected", "")
            
            passed = False
            actual = ""
            
            if test_type in {"status", "status_eq"}:
                actual = str(response.status_code)
                passed = self._compare(actual, operator, str(expected))
            elif test_type == "status_range":
                min_status = int(test.get("min", 200))
                max_status = int(test.get("max", 299))
                actual = str(response.status_code)
                passed = min_status <= response.status_code <= max_status
            elif test_type in {"responseTime", "response_time_lt"}:
                expected_ms = int(test.get("expectedMs", expected or 1000))
                actual = str(duration_ms)
                passed = duration_ms < expected_ms
            elif test_type == "header_contains":
                key = str(test.get("key", "")).strip().lower()
                expected_value = str(test.get("contains", expected))
                actual = response.headers.get(key, "")
                passed = expected_value in actual
            elif test_type == "header_eq":
                key = str(test.get("key", "")).strip().lower()
                expected_value = str(test.get("expected", ""))
                actual = response.headers.get(key, "")
                passed = actual == expected_value
            elif test_type == "body_contains":
                expected_value = str(test.get("contains", expected))
                actual = response_text
                passed = expected_value in response_text
            elif test_type in {"body", "json_path_eq", "json_path_exists", "json_path_contains"}:
                try:
                    if json_payload is None:
                        json_payload = response.json()
                    body = json_payload
                    path = str(test.get("path", target)).strip()
                    if "." in path:
                        parts = path.split(".")
                        for p in parts:
                            if isinstance(body, dict):
                                body = body.get(p)
                            else:
                                body = None
                                break
                    elif path:
                        body = body.get(path) if isinstance(body, dict) else None

                    if test_type == "json_path_exists":
                        actual = str(body) if body is not None else ""
                        passed = body is not None
                    elif test_type == "json_path_contains":
                        expected_value = str(test.get("contains", expected))
                        actual = str(body) if body is not None else ""
                        passed = expected_value in actual
                    else:
                        actual = str(body) if body is not None else ""
                        passed = self._compare(actual, operator, str(expected))
                except Exception:
                    actual = response.text[:200]
                    passed = False
            
            results.append({
                "type": test_type,
                "target": target,
                "operator": operator,
                "expected": expected,
                "actual": actual,
                "passed": passed,
            })
        
        return results

    def _compare(self, actual: str, operator: str, expected: str) -> bool:
        try:
            if operator == "eq":
                return actual == expected
            elif operator == "neq":
                return actual != expected
            elif operator == "gt":
                return float(actual) > float(expected)
            elif operator == "gte":
                return float(actual) >= float(expected)
            elif operator == "lt":
                return float(actual) < float(expected)
            elif operator == "lte":
                return float(actual) <= float(expected)
            elif operator == "contains":
                return expected in actual
            elif operator == "notContains":
                return expected not in actual
            else:
                return actual == expected
        except (ValueError, TypeError):
            return False

    async def _execute_ui(self, run: TestRun, test_case: TestCase) -> dict[str, Any]:
        output_dir = self._artifacts_dir / run.id
        output_dir.mkdir(parents=True, exist_ok=True)
        request_path = output_dir / f"{run.id}-playwright-request.json"
        payload = self._build_ui_worker_payload(run, test_case, output_dir)
        request_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if not self._ui_runner_entry.exists():
            return self._build_ui_failure_result(
                run=run,
                output_dir=output_dir,
                logs=[
                    "ui runner booted",
                    f"worker entry missing: {self._ui_runner_entry}",
                ],
                summary="Playwright UI runner 未找到，请检查 workers/ui-runner 是否存在。",
                details={"workerEntry": str(self._ui_runner_entry)},
            )

        command = [self._node_bin, str(self._ui_runner_entry), str(request_path)]
        try:
            completed = subprocess.run(
                command,
                cwd=str(self._ui_runner_dir),
                capture_output=True,
                text=True,
                timeout=self._ui_runner_timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            return self._build_ui_failure_result(
                run=run,
                output_dir=output_dir,
                logs=[
                    "ui runner booted",
                    f"node binary missing: {self._node_bin}",
                ],
                summary="未找到 Node.js 可执行文件，无法启动 Playwright UI runner。",
                details={"error": str(exc), "nodeBin": self._node_bin},
            )
        except subprocess.TimeoutExpired as exc:
            return self._build_ui_failure_result(
                run=run,
                output_dir=output_dir,
                logs=[
                    "ui runner booted",
                    f"playwright timed out after {self._ui_runner_timeout_seconds}s",
                ],
                summary="Playwright UI runner 执行超时。",
                details={"error": str(exc), "timeoutSeconds": self._ui_runner_timeout_seconds},
            )

        parsed = self._parse_worker_output(completed.stdout)
        if not parsed:
            stderr_text = (completed.stderr or "").strip()
            return self._build_ui_failure_result(
                run=run,
                output_dir=output_dir,
                logs=[
                    "ui runner booted",
                    f"worker exited with code {completed.returncode}",
                ],
                summary="Playwright UI runner 返回了无法解析的结果。",
                details={
                    "stdout": (completed.stdout or "").strip(),
                    "stderr": stderr_text,
                    "returnCode": completed.returncode,
                },
            )

        artifacts = self._register_worker_artifacts(run.id, parsed.get("artifacts"))
        logs = [str(item) for item in parsed.get("logs", []) if str(item).strip()]
        if completed.stderr and completed.stderr.strip():
            logs.append(f"stderr: {completed.stderr.strip()}")
        if not logs:
            logs = ["ui runner finished without additional logs"]

        status = str(parsed.get("status") or "failed").lower()
        if status not in {"passed", "failed"}:
            status = "failed"
        if completed.returncode != 0 and status == "passed":
            status = "failed"
        summary = str(parsed.get("summary") or "").strip()
        if not summary:
            summary = "Playwright UI runner 执行完成。" if status == "passed" else "Playwright UI runner 执行失败。"

        return {
            "status": status,
            "summary": summary,
            "logs": logs,
            "artifacts": [artifact.model_dump() for artifact in artifacts],
        }

    def _build_ui_worker_payload(
        self,
        run: TestRun,
        test_case: TestCase,
        output_dir: Path,
    ) -> dict[str, Any]:
        raw_payload = test_case.payload if isinstance(test_case.payload, dict) else {}
        viewport = raw_payload.get("viewport")
        normalized_viewport = viewport if isinstance(viewport, dict) else {"width": 1440, "height": 900}
        actions = raw_payload.get("actions")
        normalized_actions = actions if isinstance(actions, list) else []
        return {
            "runId": run.id,
            "caseTitle": test_case.title,
            "objective": test_case.objective,
            "startUrl": str(
                raw_payload.get("startUrl")
                or raw_payload.get("url")
                or raw_payload.get("baseUrl")
                or "about:blank"
            ),
            "browser": str(raw_payload.get("browser") or "chromium"),
            "headless": bool(raw_payload.get("headless", True)),
            "viewport": normalized_viewport,
            "timeoutMs": int(raw_payload.get("timeoutMs", 30000)),
            "recordTrace": bool(raw_payload.get("recordTrace", True)),
            "screenshotOnCompletion": bool(raw_payload.get("screenshotOnCompletion", True)),
            "actions": normalized_actions,
            "assertionHints": list(test_case.assertionHints),
            "steps": list(test_case.steps),
            "outputDir": str(output_dir),
        }

    def _build_ui_failure_result(
        self,
        *,
        run: TestRun,
        output_dir: Path,
        logs: list[str],
        summary: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        report_path = output_dir / f"{run.id}-ui-runner-error.json"
        report_path.write_text(
            json.dumps(
                {
                    "runId": run.id,
                    "runner": "ui",
                    "status": "failed",
                    "summary": summary,
                    "logs": logs,
                    "details": details,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        artifact = self._create_artifact(
            run_id=run.id,
            artifact_type="json",
            path=report_path,
            label="Playwright failure report",
        )
        return {
            "status": "failed",
            "summary": summary,
            "logs": logs,
            "artifacts": [artifact.model_dump()],
        }

    def _register_worker_artifacts(self, run_id: str, raw_artifacts: Any) -> list[Artifact]:
        artifacts: list[Artifact] = []
        if not isinstance(raw_artifacts, list):
            return artifacts
        for raw in raw_artifacts:
            if not isinstance(raw, dict):
                continue
            path_text = str(raw.get("path") or "").strip()
            if not path_text:
                continue
            artifact_type = str(raw.get("type") or "json").strip().lower()
            if artifact_type not in {"log", "trace", "screenshot", "report", "json"}:
                artifact_type = "json"
            label = str(raw.get("label") or f"Playwright {artifact_type}").strip() or f"Playwright {artifact_type}"
            artifact = self._create_artifact(
                run_id=run_id,
                artifact_type=artifact_type,
                path=Path(path_text),
                label=label,
            )
            artifacts.append(artifact)
        return artifacts

    def _create_artifact(
        self,
        *,
        run_id: str,
        artifact_type: str,
        path: Path,
        label: str,
    ) -> Artifact:
        artifact = Artifact(
            runId=run_id,
            type=artifact_type,
            path=str(path.resolve()),
            label=label,
        )
        self._repo._store.insert("artifacts", artifact.model_dump())
        return artifact

    @staticmethod
    def _parse_worker_output(stdout: str) -> dict[str, Any] | None:
        for line in reversed([item.strip() for item in stdout.splitlines() if item.strip()]):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

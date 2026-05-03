from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.models import Artifact, TestCase, TestRun, utc_now
from app.store import JsonStore


class LocalRunnerDispatcher:
    def __init__(
        self,
        *,
        store: JsonStore,
        artifacts_dir: Path,
        node_bin: str = "node",
        ui_runner_dir: Path | None = None,
        ui_runner_timeout_seconds: int = 180,
    ) -> None:
        self.store = store
        self.artifacts_dir = artifacts_dir
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.node_bin = node_bin
        self.ui_runner_dir = (
            ui_runner_dir
            if ui_runner_dir is not None
            else Path(__file__).resolve().parents[4] / "workers" / "ui-runner"
        ).resolve()
        self.ui_runner_entry = self.ui_runner_dir / "src" / "index.js"
        self.ui_runner_timeout_seconds = max(int(ui_runner_timeout_seconds), 10)

    def execute(self, run: TestRun, test_case: TestCase) -> TestRun:
        self.store.update(
            "runs",
            run.id,
            {
                "status": "running",
                "startedAt": utc_now(),
                "logs": ["accepted by dispatcher", f"runner={run.runnerType}"],
                "summary": "任务已进入本地执行器。",
            },
        )

        if run.runnerType == "api":
            result = self._execute_api(run, test_case)
        else:
            result = self._execute_ui(run, test_case)

        artifact_ids = [artifact["id"] for artifact in result["artifacts"]]
        final_run = self.store.update(
            "runs",
            run.id,
            {
                "status": result["status"],
                "finishedAt": utc_now(),
                "summary": result["summary"],
                "logs": result["logs"],
                "artifactIds": artifact_ids,
            },
        )
        return TestRun.model_validate(final_run)

    def _execute_api(self, run: TestRun, test_case: TestCase) -> dict[str, Any]:
        report_path = self.artifacts_dir / f"{run.id}-api-report.json"
        report = {
            "runId": run.id,
            "runner": "api",
            "caseTitle": test_case.title,
            "request": test_case.payload,
            "assertions": test_case.assertionHints,
            "status": "passed" if test_case.payload.get("url") else "failed",
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        artifact = self._create_artifact(
            run_id=run.id,
            artifact_type="json",
            path=report_path,
            label="API runner report",
        )
        return {
            "status": report["status"],
            "summary": "API runner 已生成结构化报告。",
            "logs": [
                "api runner booted",
                f"request url={test_case.payload.get('url', 'missing')}",
                f"assertions={len(test_case.assertionHints)}",
            ],
            "artifacts": [artifact.model_dump()],
        }

    def _execute_ui(self, run: TestRun, test_case: TestCase) -> dict[str, Any]:
        output_dir = self.artifacts_dir / run.id
        output_dir.mkdir(parents=True, exist_ok=True)
        request_path = output_dir / f"{run.id}-playwright-request.json"
        payload = self._build_ui_worker_payload(run, test_case, output_dir)
        request_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if not self.ui_runner_entry.exists():
            return self._build_ui_failure_result(
                run=run,
                output_dir=output_dir,
                logs=[
                    "ui runner booted",
                    f"worker entry missing: {self.ui_runner_entry}",
                ],
                summary="Playwright UI runner 未找到，请检查 workers/ui-runner 是否存在。",
                details={"workerEntry": str(self.ui_runner_entry)},
            )

        command = [self.node_bin, str(self.ui_runner_entry), str(request_path)]
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.ui_runner_dir),
                capture_output=True,
                text=True,
                timeout=self.ui_runner_timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            return self._build_ui_failure_result(
                run=run,
                output_dir=output_dir,
                logs=[
                    "ui runner booted",
                    f"node binary missing: {self.node_bin}",
                ],
                summary="未找到 Node.js 可执行文件，无法启动 Playwright UI runner。",
                details={"error": str(exc), "nodeBin": self.node_bin},
            )
        except subprocess.TimeoutExpired as exc:
            return self._build_ui_failure_result(
                run=run,
                output_dir=output_dir,
                logs=[
                    "ui runner booted",
                    f"playwright timed out after {self.ui_runner_timeout_seconds}s",
                ],
                summary="Playwright UI runner 执行超时。",
                details={"error": str(exc), "timeoutSeconds": self.ui_runner_timeout_seconds},
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
        self.store.insert("artifacts", artifact.model_dump())
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

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from app.config import Settings
from app.models import UiLocatorInspectRequest, UiLocatorInspectResponse


class UiLocatorService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def inspect(self, payload: UiLocatorInspectRequest) -> UiLocatorInspectResponse:
        worker_script = self.settings.ui_runner_dir / "src" / "locator.js"
        if not worker_script.exists():
            raise RuntimeError(f"Playwright locator worker not found: {worker_script}")

        with tempfile.TemporaryDirectory(prefix="ai-ui-locator-") as temp_dir:
            request_path = Path(temp_dir) / "locator-request.json"
            request_path.write_text(
                json.dumps(payload.model_dump(mode="json"), ensure_ascii=False),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [self.settings.node_bin, str(worker_script), str(request_path)],
                cwd=str(self.settings.ui_runner_dir),
                capture_output=True,
                text=True,
                timeout=self.settings.ui_runner_timeout_seconds,
                check=False,
            )

        stdout_text = (completed.stdout or "").strip()
        stderr_text = (completed.stderr or "").strip()
        if not stdout_text:
            detail = stderr_text or "locator worker returned empty output"
            raise RuntimeError(detail)

        parsed = self._parse_output(stdout_text)
        if completed.returncode != 0:
            message = parsed.get("summary") or stderr_text or "locator worker execution failed"
            raise RuntimeError(str(message))
        return UiLocatorInspectResponse.model_validate(parsed)

    def interactive_inspect(self, payload: UiLocatorInspectRequest) -> dict:
        worker_script = self.settings.ui_runner_dir / "src" / "interactive-locator.js"
        if not worker_script.exists():
            raise RuntimeError(f"Interactive locator worker not found: {worker_script}")

        with tempfile.TemporaryDirectory(prefix="ai-interactive-locator-") as temp_dir:
            request_path = Path(temp_dir) / "interactive-locator-request.json"
            request_path.write_text(
                json.dumps(payload.model_dump(mode="json"), ensure_ascii=False),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [self.settings.node_bin, str(worker_script), str(request_path)],
                cwd=str(self.settings.ui_runner_dir),
                capture_output=True,
                text=True,
                timeout=self.settings.ui_runner_timeout_seconds * 2,  # 交互式操作需要更长时间
                check=False,
            )

        stdout_text = (completed.stdout or "").strip()
        stderr_text = (completed.stderr or "").strip()
        if not stdout_text:
            detail = stderr_text or "interactive locator worker returned empty output"
            raise RuntimeError(detail)

        parsed = self._parse_output(stdout_text)
        if completed.returncode != 0:
            message = parsed.get("summary") or stderr_text or "interactive locator worker execution failed"
            raise RuntimeError(str(message))
        return parsed

    @staticmethod
    def _parse_output(stdout_text: str) -> dict:
        for raw_line in reversed(stdout_text.splitlines()):
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise RuntimeError("locator worker returned invalid JSON")

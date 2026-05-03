from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.models import McpRecommendation, SmitheryCommandResult, SmitheryStatus


RECOMMENDED_MCPS = [
    McpRecommendation(
        key="filesystem",
        title="Filesystem",
        category="development",
        priority=1,
        why="读取本地测试资产、模板、日志和报告，是平台最基础的输入输出能力。",
        suggestedQuery="filesystem",
        suggestedConnectionId="filesystem",
    ),
    McpRecommendation(
        key="fetch",
        title="Fetch",
        category="documentation",
        priority=2,
        why="抓 OpenAPI、PRD、帮助中心和网页说明，适合规格导入与上下文补全。",
        suggestedQuery="fetch",
        suggestedConnectionId="fetch",
    ),
    McpRecommendation(
        key="playwright",
        title="Playwright",
        category="browser-automation",
        priority=3,
        why="提供页面观察、交互和 UI 测试生成能力，是 AI+测试平台的关键眼睛。",
        suggestedQuery="playwright",
        suggestedConnectionId="playwright",
    ),
    McpRecommendation(
        key="github",
        title="GitHub",
        category="collaboration",
        priority=4,
        why="把仓库、Issue、PR 和评审流程接进来，让 Agent 能进入研发主干流程。",
        suggestedQuery="github",
        suggestedConnectionId="github",
    ),
    McpRecommendation(
        key="notion-or-jira",
        title="Notion / Jira / Linear",
        category="planning",
        priority=5,
        why="接需求文档和迭代任务，让 AI 能从需求到测试设计贯穿全流程。",
        suggestedQuery="notion jira linear",
        suggestedConnectionId="planning-suite",
    ),
    McpRecommendation(
        key="postgres",
        title="Postgres",
        category="data",
        priority=6,
        why="等平台主库切到 PostgreSQL 后，用于状态验证、报表核查和数据联动。",
        suggestedQuery="postgres",
        suggestedConnectionId="postgres",
    ),
]


MCP_NPM_PACKAGE_HINTS: dict[str, dict[str, Any]] = {
    "filesystem": {
        "package": "@modelcontextprotocol/server-filesystem",
        "tools": ["read_file", "write_file", "list_directory"],
    },
    "fetch": {
        "package": "@modelcontextprotocol/server-fetch",
        "tools": ["fetch"],
    },
    "playwright": {
        "package": "@playwright/mcp",
        "tools": ["browser_navigate", "browser_click", "browser_snapshot"],
    },
    "github": {
        "package": "github-mcp-server",
        "tools": ["list_repos", "create_issue", "list_prs"],
    },
    "notion": {
        "package": "@notionhq/notion-mcp-server",
        "tools": ["search_pages", "read_page", "create_page"],
    },
    "jira": {
        "package": "jira-mcp",
        "tools": ["search_issues", "create_issue", "transition_issue"],
    },
}


@dataclass(slots=True)
class SmitheryService:
    settings: Settings

    def status(self) -> SmitheryStatus:
        bin_path = shutil.which(self.settings.smithery_bin)
        npm_bin = shutil.which("npm")
        npx_bin = shutil.which("npx")

        if not bin_path and not (npm_bin and npx_bin):
            return SmitheryStatus(
                installed=False,
                bin=self.settings.smithery_bin,
                namespace=self.settings.smithery_namespace,
                note="未检测到 smithery / npm+npx，无法进行 MCP 在线安装。",
            )

        if not bin_path and npm_bin and npx_bin:
            return SmitheryStatus(
                installed=True,
                bin="npm/npx",
                namespace=self.settings.smithery_namespace,
                note="smithery 未安装，已启用 npm/npx 安装模式（推荐填写 MCP npm 包名）。",
            )

        version_result = self._run_smithery(["--version"])
        version = version_result.stdout.strip() if version_result.ok else None
        return SmitheryStatus(
            installed=True,
            bin=bin_path,
            version=version or None,
            namespace=self.settings.smithery_namespace,
            note="smithery CLI 已可用。下一步建议 auth login，然后搜索 filesystem / fetch / playwright。",
        )

    def recommendations(self) -> list[McpRecommendation]:
        return RECOMMENDED_MCPS

    def search(self, query: str) -> SmitheryCommandResult:
        if shutil.which(self.settings.smithery_bin):
            result = self._run_smithery(["mcp", "search", query])
            if not self._is_smithery_command_missing(result):
                return result
        return self._search_via_npm(query)

    def list_connections(self) -> SmitheryCommandResult:
        args = ["mcp", "list"]
        if self.settings.smithery_namespace:
            args.extend(["--namespace", self.settings.smithery_namespace])
        if shutil.which(self.settings.smithery_bin):
            result = self._run_smithery(args)
            if not self._is_smithery_command_missing(result):
                return result
        return SmitheryCommandResult(
            ok=True,
            command=["npm", "connections", "list"],
            stdout="npm 模式不维护远端 connection 列表，请以 /settings 中 mcpServers 为准。",
            stderr="",
            exitCode=0,
        )

    def add_connection(
        self,
        *,
        server: str,
        connection_id: str,
        metadata: dict | None,
    ) -> SmitheryCommandResult:
        args = ["mcp", "add", server, "--id", connection_id]
        if self.settings.smithery_namespace:
            args.extend(["--namespace", self.settings.smithery_namespace])
        if metadata:
            args.extend(["--metadata", json.dumps(metadata, ensure_ascii=False)])
        if shutil.which(self.settings.smithery_bin):
            result = self._run_smithery(args)
            if not self._is_smithery_command_missing(result):
                return result
        return self._install_via_npm(
            server=server,
            connection_id=connection_id,
            metadata=metadata or {},
        )

    def list_tools(self, connection_id: str, prefix: str | None = None) -> SmitheryCommandResult:
        tool_hint = MCP_NPM_PACKAGE_HINTS.get(connection_id, {}).get("tools", [])
        if not shutil.which(self.settings.smithery_bin):
            return SmitheryCommandResult(
                ok=True,
                command=["npm", "tools", "list", connection_id],
                stdout="\n".join(tool_hint),
                stderr=(
                    "当前为 npm 配置模式，工具列表为预置提示。"
                    if tool_hint
                    else "当前为 npm 配置模式，未发现预置工具提示。"
                ),
                exitCode=0,
            )

        args = ["tool", "list", connection_id]
        if prefix:
            args.append(prefix)
        result = self._run_smithery(args)
        if not self._is_smithery_command_missing(result):
            return result
        return SmitheryCommandResult(
            ok=True,
            command=["npm", "tools", "list", connection_id],
            stdout="\n".join(tool_hint),
            stderr="当前环境未启用 smithery CLI，已回退预置工具列表。",
            exitCode=0,
        )

    def get_tool(self, connection_id: str, tool_name: str) -> SmitheryCommandResult:
        if not shutil.which(self.settings.smithery_bin):
            return SmitheryCommandResult(
                ok=True,
                command=["npm", "tools", "get", connection_id, tool_name],
                stdout=json.dumps(
                    {
                        "name": tool_name,
                        "connectionId": connection_id,
                        "mode": "npm-config",
                        "note": "当前为 npm 配置模式，详细 schema 需在运行时由 MCP 服务端返回。",
                    },
                    ensure_ascii=False,
                ),
                stderr="",
                exitCode=0,
            )
        result = self._run_smithery(["tool", "get", connection_id, tool_name])
        if not self._is_smithery_command_missing(result):
            return result
        return SmitheryCommandResult(
            ok=True,
            command=["npm", "tools", "get", connection_id, tool_name],
            stdout=json.dumps(
                {
                    "name": tool_name,
                    "connectionId": connection_id,
                    "mode": "npm-config",
                    "note": "当前环境未启用 smithery CLI，返回预置工具描述。",
                },
                ensure_ascii=False,
            ),
            stderr="",
            exitCode=0,
        )

    def call_tool(self, connection_id: str, tool_name: str, payload: dict) -> SmitheryCommandResult:
        if not shutil.which(self.settings.smithery_bin):
            return SmitheryCommandResult(
                ok=False,
                command=["npm", "tools", "call", connection_id, tool_name],
                stdout="",
                stderr=(
                    "当前环境未安装 smithery，无法在设置页直接调用 MCP 工具。"
                    "已可将该 MCP 配置写入 AI settings，运行时由 Agent 调用。"
                ),
                exitCode=2,
            )
        result = self._run_smithery(
            ["tool", "call", connection_id, tool_name, json.dumps(payload, ensure_ascii=False)]
        )
        if not self._is_smithery_command_missing(result):
            return result
        return SmitheryCommandResult(
            ok=False,
            command=["npm", "tools", "call", connection_id, tool_name],
            stdout="",
            stderr=(
                "当前环境未安装 smithery，无法在设置页直接调用 MCP 工具。"
                "已可将该 MCP 配置写入 AI settings，运行时由 Agent 调用。"
            ),
            exitCode=2,
        )

    def _run_smithery(self, args: list[str]) -> SmitheryCommandResult:
        command = [self.settings.smithery_bin, *args]
        return self._run_command(command)

    def _run_command(self, command: list[str]) -> SmitheryCommandResult:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            return SmitheryCommandResult(
                ok=False,
                command=command,
                stdout="",
                stderr=f"command not found: {command[0]}",
                exitCode=127,
            )

        return SmitheryCommandResult(
            ok=completed.returncode == 0,
            command=command,
            stdout=completed.stdout,
            stderr=completed.stderr,
            exitCode=completed.returncode,
        )

    def _search_via_npm(self, query: str) -> SmitheryCommandResult:
        npm_bin = shutil.which("npm")
        if not npm_bin:
            return SmitheryCommandResult(
                ok=False,
                command=["npm", "search", "--json", "--searchlimit=30", query],
                stdout="",
                stderr="npm command not found",
                exitCode=127,
            )

        result = self._run_command([npm_bin, "search", "--json", "--searchlimit=30", query])
        if not result.ok:
            return result

        try:
            parsed = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return SmitheryCommandResult(
                ok=False,
                command=[npm_bin, "search", "--json", "--searchlimit=30", query],
                stdout="",
                stderr="npm search returned invalid JSON",
                exitCode=3,
            )

        rows: list[str] = []
        for entry in parsed if isinstance(parsed, list) else []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            if not name:
                continue
            desc = str(entry.get("description", "")).strip()
            kws = entry.get("keywords")
            kw_text = " ".join(kws) if isinstance(kws, list) else str(kws or "")
            lowered = f"{name} {desc} {kw_text}".lower()
            if "mcp" not in lowered and "model context protocol" not in lowered:
                continue
            rows.append(
                json.dumps(
                    {
                        "name": name,
                        "qualifiedName": name,
                        "description": desc,
                        "connectionUrl": "",
                    },
                    ensure_ascii=False,
                )
            )

        if not rows:
            for key, hint in MCP_NPM_PACKAGE_HINTS.items():
                if query.lower() in key.lower():
                    rows.append(
                        json.dumps(
                            {
                                "name": key,
                                "qualifiedName": key,
                                "description": f"推荐包：{hint['package']}",
                                "connectionUrl": "",
                            },
                            ensure_ascii=False,
                        )
                    )

        return SmitheryCommandResult(
            ok=True,
            command=[npm_bin, "search", "--json", "--searchlimit=30", query],
            stdout="\n".join(rows),
            stderr="",
            exitCode=0,
        )

    def _install_via_npm(
        self,
        *,
        server: str,
        connection_id: str,
        metadata: dict[str, Any],
    ) -> SmitheryCommandResult:
        npm_bin = shutil.which("npm")
        if not npm_bin:
            return SmitheryCommandResult(
                ok=False,
                command=["npm", "view", server],
                stdout="",
                stderr="npm command not found",
                exitCode=127,
            )

        package_name = self._resolve_npm_package(server=server, metadata=metadata)
        if not package_name:
            return SmitheryCommandResult(
                ok=False,
                command=["npm", "view", server],
                stdout="",
                stderr="未提供可安装的 npm packageName",
                exitCode=4,
            )

        view_result = self._run_command([npm_bin, "view", package_name, "name", "version", "--json"])
        if not view_result.ok:
            return SmitheryCommandResult(
                ok=False,
                command=[npm_bin, "view", package_name, "name", "version", "--json"],
                stdout=view_result.stdout,
                stderr=view_result.stderr or f"npm 包不存在或网络不可达：{package_name}",
                exitCode=view_result.exitCode,
            )

        env = metadata.get("env") if isinstance(metadata.get("env"), dict) else {}
        args = metadata.get("args") if isinstance(metadata.get("args"), list) else []
        safe_args = [str(arg) for arg in args if str(arg).strip()]

        preset_tools = MCP_NPM_PACKAGE_HINTS.get(server, {}).get("tools", [])
        server_config = {
            "name": connection_id,
            "command": "npx",
            "args": ["-y", package_name, *safe_args],
            "env": {str(k): str(v) for k, v in env.items()},
            "enabled": True,
            "builtIn": False,
            "source": "npm",
            "tools": preset_tools,
        }
        payload = {
            "mode": "npm",
            "installed": True,
            "packageName": package_name,
            "connectionId": connection_id,
            "config": server_config,
            "tools": preset_tools,
            "note": "已验证 npm 包可用，配置已生成。首次调用时将由 npx 自动下载执行。",
        }
        return SmitheryCommandResult(
            ok=True,
            command=[npm_bin, "view", package_name, "name", "version", "--json"],
            stdout=json.dumps(payload, ensure_ascii=False),
            stderr="",
            exitCode=0,
        )

    def _resolve_npm_package(self, *, server: str, metadata: dict[str, Any]) -> str:
        package_name = str(metadata.get("packageName", "")).strip()
        if package_name:
            return package_name

        normalized = server.strip().lower()
        if normalized in MCP_NPM_PACKAGE_HINTS:
            return str(MCP_NPM_PACKAGE_HINTS[normalized]["package"])

        if normalized.startswith("@") or "/" in normalized:
            return normalized

        if normalized.startswith("mcp-") or normalized.startswith("@modelcontextprotocol/"):
            return normalized

        return f"@modelcontextprotocol/server-{normalized}"

    def _is_smithery_command_missing(self, result: SmitheryCommandResult) -> bool:
        if result.ok:
            return False
        stderr = str(result.stderr or "").lower()
        return "command not found" in stderr and "smithery" in stderr

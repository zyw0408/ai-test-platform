from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


PLATFORM_API_URL = os.getenv("TEST_PLATFORM_API_URL", "http://127.0.0.1:8000")
PLATFORM_API_TOKEN = os.getenv("TEST_PLATFORM_API_TOKEN", "")
mcp = FastMCP("test-platform-mcp")


def _headers() -> dict[str, str]:
    token = PLATFORM_API_TOKEN.strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


async def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.request(
            method,
            f"{PLATFORM_API_URL}{path}",
            json=payload,
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


@mcp.tool(name="project.list")
async def project_list() -> Any:
    return await _request("GET", "/projects")


@mcp.tool(name="spec.ingest")
async def spec_ingest(project_id: str, source_type: str, title: str, content: str) -> Any:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{PLATFORM_API_URL}/specs/ingest",
            data={
                "projectId": project_id,
                "sourceType": source_type,
                "title": title,
                "content": content,
            },
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


@mcp.tool(name="case.generate")
async def case_generate(project_id: str, spec_id: str, kinds: list[str] | None = None) -> Any:
    return await _request(
        "POST",
        "/cases/generate",
        {
            "projectId": project_id,
            "specId": spec_id,
            "kinds": kinds or ["api", "ui"],
        },
    )


@mcp.tool(name="run.start")
async def run_start(project_id: str, case_id: str, runner_type: str) -> Any:
    return await _request(
        "POST",
        "/runs",
        {
            "projectId": project_id,
            "caseId": case_id,
            "runnerType": runner_type,
        },
    )


@mcp.tool(name="run.get")
async def run_get(run_id: str) -> Any:
    return await _request("GET", f"/runs/{run_id}")


@mcp.tool(name="report.summary")
async def report_summary(run_id: str) -> Any:
    return await _request("GET", f"/reports/run/{run_id}")


@mcp.tool(name="security.scan")
async def security_scan(
    project_id: str,
    collection_ids: list[str] | None = None,
    target_url: str | None = None,
    scan_types: list[str] | None = None,
    deep_scan: bool = True,
    async_mode: bool = True,
    max_discovered_urls: int = 8,
) -> Any:
    payload = {
        "projectId": project_id,
        "collectionIds": collection_ids or [],
        "targetUrl": target_url,
        "maxDiscoveredUrls": max(1, min(int(max_discovered_urls), 30)),
        "scanTypes": scan_types
        or [
            "owasp_api",
            "pii_scan",
            "auth_bypass",
            "security_headers",
            "cors_misconfig",
            "xss_reflection",
            "error_leak",
            "insecure_transport",
            "idor_enumeration",
            "path_traversal",
            "ssrf_probe",
            "file_upload_security",
            "command_template_injection",
            "jwt_session_security",
            "rate_limit_bruteforce",
        ],
        "deepScan": bool(deep_scan),
    }
    path = "/security/scan/start" if async_mode else "/security/scan"
    return await _request("POST", path, payload)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

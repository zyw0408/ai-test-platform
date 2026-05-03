from __future__ import annotations

from typing import Any

from app.models import SourceSpec, TestCase
from app.services.providers import ModelProvider


def _spec_facts(spec: SourceSpec) -> dict[str, str]:
    text = spec.content[:1200]
    title = spec.title
    return {"title": title, "excerpt": text}


def _fallback_cases(spec: SourceSpec, project_id: str, kinds: list[str]) -> list[TestCase]:
    facts = _spec_facts(spec)
    cases: list[TestCase] = []
    if "api" in kinds:
        cases.append(
            TestCase(
                projectId=project_id,
                specId=spec.id,
                kind="api",
                title=f"{facts['title']} API 冒烟",
                objective="验证核心接口可访问、主路径返回成功。",
                steps=[
                    "根据规格提取主接口路径、请求参数和鉴权要求。",
                    "构造一条主成功路径请求。",
                    "断言状态码与关键字段。",
                ],
                assertionHints=["状态码为 200", "响应体包含业务主键"],
                payload={
                    "method": "GET",
                    "url": spec.metadata.get("location") or "https://example.com/api/health",
                    "excerpt": facts["excerpt"],
                },
            )
        )
    if "ui" in kinds:
        cases.append(
            TestCase(
                projectId=project_id,
                specId=spec.id,
                kind="ui",
                title=f"{facts['title']} UI 冒烟",
                objective="验证核心页面链路可访问，并生成基础证据。",
                steps=[
                    "打开起始页面并等待关键元素出现。",
                    "执行一条代表性业务动作。",
                    "断言成功提示或页面状态变化。",
                ],
                assertionHints=["页面无严重错误", "生成 trace 与截图"],
                payload={
                    "startUrl": "https://example.com",
                    "excerpt": facts["excerpt"],
                },
            )
        )
    return cases


def _coerce_cases(
    payload: dict[str, Any] | None,
    *,
    project_id: str,
    spec: SourceSpec,
    kinds: list[str],
) -> list[TestCase]:
    if not payload:
        return _fallback_cases(spec, project_id, kinds)

    cases: list[TestCase] = []
    for item in payload.get("apiCases", []):
        cases.append(
            TestCase(
                projectId=project_id,
                specId=spec.id,
                kind="api",
                title=item.get("title", f"{spec.title} API 冒烟"),
                objective=item.get("objective", "验证接口主链路。"),
                steps=item.get("steps", []),
                assertionHints=item.get("assertionHints", []),
                payload=item.get("payload", {}),
            )
        )
    for item in payload.get("uiCases", []):
        cases.append(
            TestCase(
                projectId=project_id,
                specId=spec.id,
                kind="ui",
                title=item.get("title", f"{spec.title} UI 冒烟"),
                objective=item.get("objective", "验证页面主链路。"),
                steps=item.get("steps", []),
                assertionHints=item.get("assertionHints", []),
                payload=item.get("payload", {}),
            )
        )

    return [case for case in cases if case.kind in kinds] or _fallback_cases(
        spec, project_id, kinds
    )


async def generate_cases(
    *,
    provider: ModelProvider,
    spec: SourceSpec,
    project_id: str,
    kinds: list[str],
) -> list[TestCase]:
    prompt = (
        "Generate concise API and UI smoke tests for the following source spec.\n"
        f"Title: {spec.title}\n"
        f"SourceKind: {spec.kind}\n"
        f"Content:\n{spec.content[:5000]}"
    )
    result = await provider.complete_json(prompt)
    return _coerce_cases(result, project_id=project_id, spec=spec, kinds=kinds)

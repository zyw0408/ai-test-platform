from __future__ import annotations

from pathlib import Path

import httpx

from app.models import SourceSpec


async def build_source_spec(
    *,
    project_id: str,
    source_type: str,
    title: str | None,
    source_url: str | None,
    content: str | None,
    file_name: str | None,
    file_bytes: bytes | None,
) -> SourceSpec:
    resolved_title = title or "未命名规格"
    resolved_location = ""
    resolved_content = content or ""

    if source_type == "url":
        if not source_url:
            raise ValueError("sourceUrl is required when sourceType=url")
        async with httpx.AsyncClient(timeout=15.0) as client:
          response = await client.get(source_url)
        response.raise_for_status()
        resolved_location = source_url
        resolved_content = response.text
        resolved_title = title or source_url.rsplit("/", 1)[-1] or "远程规格"
    elif source_type == "file":
        if not file_name or file_bytes is None:
            raise ValueError("file is required when sourceType=file")
        resolved_title = title or Path(file_name).name
        resolved_location = file_name
        resolved_content = file_bytes.decode("utf-8", errors="ignore")
    elif source_type == "text":
        if not resolved_content:
            raise ValueError("content is required when sourceType=text")
        resolved_title = title or "手工录入规格"
    else:
        raise ValueError(f"unsupported source type: {source_type}")

    return SourceSpec(
        projectId=project_id,
        sourceType=source_type,
        title=resolved_title,
        location=resolved_location,
        content=resolved_content,
    )

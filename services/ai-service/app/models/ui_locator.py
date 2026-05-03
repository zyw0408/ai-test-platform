from __future__ import annotations

from pydantic import BaseModel, Field


class UiLocatorInspectRequest(BaseModel):
    url: str
    browser: str = "chromium"
    headless: bool = True
    limit: int = 40
    waitUntil: str = "load"
    timeoutMs: int = 15000


class UiLocatorCandidate(BaseModel):
    selector: str
    strategy: str = ""
    description: str = ""
    label: str = ""
    tagName: str = ""
    role: str = ""
    text: str = ""
    placeholder: str = ""
    testId: str = ""
    alternatives: list[str] = Field(default_factory=list)


class UiLocatorInspectResponse(BaseModel):
    url: str = ""
    title: str = ""
    browser: str = "chromium"
    logs: list[str] = Field(default_factory=list)
    candidates: list[UiLocatorCandidate] = Field(default_factory=list)
    summary: str = ""

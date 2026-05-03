from __future__ import annotations
from typing import Literal
from pydantic import BaseModel

SourceType = Literal["url", "file", "text"]
TestCaseKind = Literal["api", "ui", "manual", "security", "performance", "automation"]
RunStatus = Literal["queued", "running", "passed", "failed"]
RunnerType = Literal["api", "ui"]
ArtifactType = Literal["log", "trace", "screenshot", "report", "json"]
BrowserName = Literal["chromium", "firefox", "webkit"]
AuthMethod = Literal["password", "sms", "wechat"]
UserRole = Literal["admin", "tester", "viewer"]
RequirementStatus = Literal["draft", "analyzing", "analyzed", "failed"]
AiOperationStatus = Literal["queued", "running", "succeeded", "failed"]
AiOperationType = Literal["requirement_analysis"]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
ApiAuthType = Literal["none", "bearer", "basic", "apiKey"]
ApiBodyMode = Literal["none", "raw", "json", "form"]
ApiAssertionType = Literal[
    "status_eq",
    "status_range",
    "json_path_eq",
    "json_path_exists",
    "json_path_contains",
    "header_contains",
    "header_eq",
    "body_contains",
    "response_time_lt",
]

class PageMeta(BaseModel):
    total: int
    page: int
    pageSize: int
    hasNext: bool

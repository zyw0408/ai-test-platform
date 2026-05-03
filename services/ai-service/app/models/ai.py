from pydantic import BaseModel, Field
from typing import Any

class McpRecommendation(BaseModel):
    key: str
    title: str
    category: str
    priority: int
    why: str
    suggestedQuery: str
    suggestedConnectionId: str

class SmitheryStatus(BaseModel):
    installed: bool
    bin: str
    version: str | None = None
    namespace: str | None = None
    note: str

class SmitheryCommandResult(BaseModel):
    ok: bool
    command: list[str]
    stdout: str = ""
    stderr: str = ""
    exitCode: int | None = None

class AIChatMessage(BaseModel):
    role: str
    content: str

class AIChatRequest(BaseModel):
    messages: list[AIChatMessage]
    context: str | None = None
    projectId: str | None = None
    sessionId: str | None = None
    page: str | None = None
    stream: bool = True

class AIChatResponse(BaseModel):
    content: str
    model: str = ""
    sessionId: str | None = None
    taskType: str | None = None
    agentsUsed: list[str] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)

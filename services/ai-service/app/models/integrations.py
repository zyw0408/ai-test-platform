from pydantic import BaseModel, Field, AliasChoices, ConfigDict
from typing import Any, List, Optional

class SmitheryStatus(BaseModel):
    installed: bool
    bin: str | None = None
    version: str | None = None
    namespace: str | None = None
    note: str | None = None

class McpRecommendation(BaseModel):
    key: str
    title: str
    category: str
    priority: int
    why: str
    suggestedQuery: str = Field(validation_alias=AliasChoices("suggestedQuery", "suggested_query"))
    suggestedConnectionId: str = Field(validation_alias=AliasChoices("suggestedConnectionId", "suggested_connection_id"))

class SmitherySearchResponse(BaseModel):
    query: str
    result: Any

class SmitheryCommandResult(BaseModel):
    ok: bool
    stdout: str
    stderr: str
    exitCode: int = Field(validation_alias=AliasChoices("exitCode", "exit_code"))

class SmitheryConnectRequest(BaseModel):
    server: str
    connectionId: str = Field(validation_alias=AliasChoices("connectionId", "connection_id"))
    metadata: dict[str, Any] = Field(default_factory=dict)

class SmitheryToolListResponse(BaseModel):
    connectionId: str = Field(validation_alias=AliasChoices("connectionId", "connection_id"))
    prefix: str | None = None
    result: Any


class SmitheryToolCallRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)

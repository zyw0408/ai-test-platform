from pydantic import BaseModel, Field, AliasChoices, ConfigDict, field_validator
from typing import Any
import json
from app.core.utils import new_id, utc_now
from .base import TestCaseKind, RunnerType, RunStatus, ArtifactType

class TestCase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str = Field(default_factory=lambda: new_id("case"))
    projectId: str = Field(validation_alias=AliasChoices("projectId", "project_id"))
    specId: str = Field(default="", validation_alias=AliasChoices("specId", "spec_id"))
    kind: TestCaseKind = "manual"
    title: str
    objective: str = ""
    steps: list[str] = Field(default_factory=list, validation_alias=AliasChoices("steps", "steps_json"))
    assertionHints: list[str] = Field(default_factory=list, validation_alias=AliasChoices("assertionHints", "assertion_hints_json"))
    payload: dict[str, Any] = Field(default_factory=dict, validation_alias=AliasChoices("payload", "payload_json"))
    createdBy: str | None = Field(default=None, validation_alias=AliasChoices("createdBy", "created_by"))
    createdAt: str = Field(default_factory=utc_now, validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: str = Field(default_factory=utc_now, validation_alias=AliasChoices("updatedAt", "updated_at"))

    @field_validator("steps", "assertionHints", mode="before")
    @classmethod
    def parse_json_list(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return []
        return v if isinstance(v, list) else []

    @field_validator("payload", mode="before")
    @classmethod
    def parse_json_dict(cls, v: Any) -> dict[str, Any]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {}
        return v if isinstance(v, dict) else {}

class Artifact(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str = Field(default_factory=lambda: new_id("artifact"))
    runId: str = Field(validation_alias=AliasChoices("runId", "run_id"))
    type: ArtifactType
    path: str
    label: str

class TestRun(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str = Field(default_factory=lambda: new_id("run"))
    projectId: str = Field(validation_alias=AliasChoices("projectId", "project_id"))
    caseId: str = Field(validation_alias=AliasChoices("caseId", "case_id"))
    runnerType: RunnerType = Field(validation_alias=AliasChoices("runnerType", "runner_type"))
    status: RunStatus = "queued"
    startedAt: str | None = Field(default=None, validation_alias=AliasChoices("startedAt", "started_at"))
    finishedAt: str | None = Field(default=None, validation_alias=AliasChoices("finishedAt", "finished_at"))
    summary: str = ""
    logs: list[str] = Field(default_factory=list, validation_alias=AliasChoices("logs", "logs_json"))
    artifactIds: list[str] = Field(default_factory=list, validation_alias=AliasChoices("artifactIds", "artifact_ids_json"))
    triggeredBy: str | None = Field(default=None, validation_alias=AliasChoices("triggeredBy", "triggered_by"))
    sequential: bool = Field(default=False, validation_alias=AliasChoices("sequential", "sequential"))
    createdAt: str = Field(default_factory=utc_now, validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: str = Field(default_factory=utc_now, validation_alias=AliasChoices("updatedAt", "updated_at"))

    @field_validator("logs", mode="before")
    @classmethod
    def parse_json_list(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return []
        return v if isinstance(v, list) else []

    @field_validator("artifactIds", mode="before")
    @classmethod
    def parse_json_list(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return []
        return v if isinstance(v, list) else []
    triggeredBy: str | None = Field(default=None, validation_alias=AliasChoices("triggeredBy", "triggered_by"))
    sequential: bool = Field(default=False, validation_alias=AliasChoices("sequential", "sequential"))
    createdAt: str = Field(default_factory=utc_now, validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: str = Field(default_factory=utc_now, validation_alias=AliasChoices("updatedAt", "updated_at"))

class TestCaseListResponse(BaseModel):
    items: list[TestCase]
    total: int
    page: int
    pageSize: int
    hasNext: bool

class TestCaseCreateRequest(BaseModel):
    projectId: str
    specId: str
    kind: TestCaseKind
    title: str = Field(min_length=1, max_length=256)
    objective: str = Field(default="", max_length=4000)
    steps: list[str] = Field(default_factory=list, max_length=200)
    assertionHints: list[str] = Field(default_factory=list, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)

class TestCaseUpdateRequest(BaseModel):
    projectId: str | None = None
    specId: str | None = None
    kind: TestCaseKind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=256)
    objective: str | None = Field(default=None, max_length=4000)
    steps: list[str] | None = Field(default=None, max_length=200)
    assertionHints: list[str] | None = Field(default=None, max_length=200)
    payload: dict[str, Any] | None = None

class TestRunCreateRequest(BaseModel):
    caseId: str
    projectId: str
    runnerType: RunnerType
    sequential: bool = False

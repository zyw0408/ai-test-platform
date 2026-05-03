from pydantic import BaseModel, Field, AliasChoices, ConfigDict
from datetime import datetime
from typing import Any
from .base import RequirementStatus, AiOperationType, AiOperationStatus

class RequirementCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    projectId: str = Field(validation_alias=AliasChoices("projectId", "project_id"))
    title: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=20000)
    sourceSpecId: str | None = Field(default=None, max_length=64, validation_alias=AliasChoices("sourceSpecId", "source_spec_id"))
    tags: list[str] = Field(default_factory=list)

class RequirementUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    title: str | None = Field(default=None, min_length=1, max_length=256)
    content: str | None = Field(default=None, min_length=1, max_length=20000)
    sourceSpecId: str | None = Field(default=None, max_length=64, validation_alias=AliasChoices("sourceSpecId", "source_spec_id"))
    tags: list[str] | None = None
    status: RequirementStatus | None = None

class RequirementPublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    projectId: str = Field(validation_alias=AliasChoices("projectId", "project_id"))
    sourceSpecId: str | None = Field(default=None, validation_alias=AliasChoices("sourceSpecId", "source_spec_id"))
    title: str
    content: str
    status: RequirementStatus
    tags: list[str] = Field(default_factory=list)
    latestAnalysisVersion: int | None = Field(default=None, validation_alias=AliasChoices("latestAnalysisVersion", "latest_analysis_version"))
    createdBy: str | None = Field(default=None, validation_alias=AliasChoices("createdBy", "created_by"))
    createdAt: str = Field(validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: str = Field(validation_alias=AliasChoices("updatedAt", "updated_at"))

class RequirementAnalysisPublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    requirementId: str = Field(validation_alias=AliasChoices("requirementId", "requirement_id"))
    version: int
    summary: str
    functionalRequirements: list[str] = Field(default_factory=list, validation_alias=AliasChoices("functionalRequirements", "functional_requirements"))
    nonFunctionalRequirements: list[str] = Field(default_factory=list, validation_alias=AliasChoices("nonFunctionalRequirements", "non_functional_requirements"))
    acceptanceCriteria: list[str] = Field(default_factory=list, validation_alias=AliasChoices("acceptanceCriteria", "acceptance_criteria"))
    risks: list[str] = Field(default_factory=list)
    testFocus: list[str] = Field(default_factory=list, validation_alias=AliasChoices("testFocus", "test_focus"))
    assumptions: list[str] = Field(default_factory=list)
    source: str
    aiOperationId: str | None = Field(default=None, validation_alias=AliasChoices("aiOperationId", "ai_operation_id"))
    createdAt: str = Field(validation_alias=AliasChoices("createdAt", "created_at"))

class AiOperationPublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    operationType: AiOperationType = Field(validation_alias=AliasChoices("operationType", "operation_type"))
    targetType: str = Field(validation_alias=AliasChoices("targetType", "target_type"))
    targetId: str = Field(validation_alias=AliasChoices("targetId", "target_id"))
    status: AiOperationStatus
    requestPayload: dict[str, Any] | None = Field(default=None, validation_alias=AliasChoices("requestPayload", "request_payload"))
    responsePayload: dict[str, Any] | None = Field(default=None, validation_alias=AliasChoices("responsePayload", "response_payload"))
    errorMessage: str | None = Field(default=None, validation_alias=AliasChoices("errorMessage", "error_message"))
    createdBy: str | None = Field(default=None, validation_alias=AliasChoices("createdBy", "created_by"))
    attemptCount: int = Field(validation_alias=AliasChoices("attemptCount", "attempt_count"))
    createdAt: str = Field(validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: str = Field(validation_alias=AliasChoices("updatedAt", "updated_at"))
    startedAt: str | None = Field(default=None, validation_alias=AliasChoices("startedAt", "started_at"))
    finishedAt: str | None = Field(default=None, validation_alias=AliasChoices("finishedAt", "finished_at"))

class RequirementAnalyzeResult(BaseModel):
    operation: AiOperationPublic
    analysis: RequirementAnalysisPublic | None = None

class RequirementListResponse(BaseModel):
    items: list[RequirementPublic]
    total: int
    page: int
    pageSize: int
    hasNext: bool

class RequirementBatchDeleteRequest(BaseModel):
    requirementIds: list[str] = Field(min_length=1, max_length=1000, validation_alias=AliasChoices("requirementIds", "requirement_ids"))

class RequirementImportResult(BaseModel):
    count: int
    requirementIds: list[str] = Field(default_factory=list, validation_alias=AliasChoices("requirementIds", "requirement_ids"))

class RequirementImportPreviewResult(BaseModel):
    total: int
    valid: int
    invalid: int
    previews: list[RequirementCreateRequest] = Field(default_factory=list)

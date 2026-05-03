from pydantic import BaseModel, Field, ConfigDict, AliasChoices
from typing import Any
from .base import HttpMethod, ApiAuthType, ApiBodyMode, ApiAssertionType

class ApiKeyValue(BaseModel):
    key: str
    value: str = ""
    enabled: bool = True
    description: str = ""

class ApiCollectionPublic(BaseModel):
    id: str
    projectId: str
    name: str
    description: str = ""
    variables: dict[str, str] = Field(default_factory=dict)
    createdBy: str | None = None
    createdAt: str
    updatedAt: str

class ApiCollectionCreateRequest(BaseModel):
    projectId: str
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    variables: dict[str, str] = Field(default_factory=dict)

class ApiEnvironmentPublic(BaseModel):
    id: str
    collectionId: str
    name: str
    variables: dict[str, str] = Field(default_factory=dict)
    isDefault: bool = False
    createdBy: str | None = None
    createdAt: str
    updatedAt: str

class ApiRequestPublic(BaseModel):
    id: str
    collectionId: str
    parentId: str | None = None
    name: str
    groupName: str = "default"
    tags: list[str] = Field(default_factory=list)
    method: HttpMethod
    url: str
    query: list[ApiKeyValue] = Field(default_factory=list)
    headers: list[ApiKeyValue] = Field(default_factory=list)
    bodyMode: ApiBodyMode = "none"
    bodyRaw: str = ""
    bodyForm: list[ApiKeyValue] = Field(default_factory=list)
    authType: ApiAuthType = "none"
    auth: dict[str, Any] = Field(default_factory=dict)
    verifySsl: bool = True
    tls: dict[str, Any] = Field(default_factory=dict)
    tests: list[dict[str, Any]] = Field(default_factory=list)
    preScript: str = ""
    testScript: str = ""
    isFolder: bool = False
    sortOrder: int = 0
    createdBy: str | None = None
    createdAt: str
    updatedAt: str

class ApiAssertionResult(BaseModel):
    type: ApiAssertionType
    passed: bool
    message: str
    name: str | None = None

class ApiRequestRunPublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    requestId: str = Field(validation_alias=AliasChoices("requestId", "request_id"))
    collectionId: str = Field(validation_alias=AliasChoices("collectionId", "collection_id"))
    method: HttpMethod
    url: str
    statusCode: int | None = Field(None, validation_alias=AliasChoices("statusCode", "status_code"))
    durationMs: int = Field(validation_alias=AliasChoices("durationMs", "duration_ms"))
    success: bool
    responseHeaders: dict[str, Any] = Field(default_factory=dict, validation_alias=AliasChoices("responseHeaders", "response_headers"))
    responseBody: str = Field("", validation_alias=AliasChoices("responseBody", "response_body", "body_text"))
    responseSize: int = Field(0, validation_alias=AliasChoices("responseSize", "response_size"))
    errorMessage: str | None = Field(None, validation_alias=AliasChoices("errorMessage", "error_message"))
    assertions: list[ApiAssertionResult] = Field(default_factory=list)
    extractedVariables: dict[str, str] = Field(default_factory=dict, validation_alias=AliasChoices("extractedVariables", "extracted_variables"))
    createdBy: str | None = Field(None, validation_alias=AliasChoices("createdBy", "created_by"))
    createdAt: str = Field(validation_alias=AliasChoices("createdAt", "created_at"))

    @property
    def body_text(self) -> str:
        return self.responseBody

    @property
    def duration_ms(self) -> int:
        return self.durationMs

    @property
    def status_code(self) -> int | None:
        return self.statusCode

class SourceSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    orgId: str = Field("DEFAULT_ORG", validation_alias=AliasChoices("orgId", "org_id"))
    projectId: str = Field(validation_alias=AliasChoices("projectId", "project_id"))
    title: str = Field(validation_alias=AliasChoices("title", "name"))
    kind: str = Field("swagger", validation_alias=AliasChoices("kind", "type"))
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias=AliasChoices("metadata", "metadata_json"))
    createdBy: str | None = Field(None, validation_alias=AliasChoices("createdBy", "created_by"))
    createdAt: str = Field(validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: str = Field(validation_alias=AliasChoices("updatedAt", "updated_at"))

class ApiCollectionUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=1000)
    variables: dict[str, str] | None = None

class ApiRequestCreateRequest(BaseModel):
    collectionId: str
    name: str = Field(min_length=1, max_length=128)
    groupName: str = "default"
    tags: list[str] = []
    method: HttpMethod = "GET"
    url: str = ""
    query: list[ApiKeyValue] = []
    headers: list[ApiKeyValue] = []
    bodyMode: ApiBodyMode = "none"
    bodyRaw: str = ""
    bodyForm: list[ApiKeyValue] = []
    authType: ApiAuthType = "none"
    auth: dict[str, Any] = {}
    verifySsl: bool = True
    tls: dict[str, Any] = {}
    tests: list[dict[str, Any]] = []
    preScript: str = ""
    testScript: str = ""
    isFolder: bool = False
    sortOrder: int = 0

class ApiRequestUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    groupName: str | None = None
    tags: list[str] | None = None
    method: HttpMethod | None = None
    url: str | None = None
    query: list[ApiKeyValue] | None = None
    headers: list[ApiKeyValue] | None = None
    bodyMode: ApiBodyMode | None = None
    bodyRaw: str | None = None
    bodyForm: list[ApiKeyValue] | None = None
    authType: ApiAuthType | None = None
    auth: dict[str, Any] | None = None
    verifySsl: bool | None = None
    tls: dict[str, Any] | None = None
    tests: list[dict[str, Any]] | None = None
    preScript: str | None = None
    testScript: str | None = None
    isFolder: bool | None = None
    sortOrder: int | None = None

class ApiEnvironmentCreateRequest(BaseModel):
    collectionId: str
    name: str = Field(min_length=1, max_length=128)
    variables: dict[str, str] = {}
    isDefault: bool = False

class ApiEnvironmentUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    variables: dict[str, str] | None = None
    isDefault: bool | None = None

class SourceSpecPublic(SourceSpec):
    pass

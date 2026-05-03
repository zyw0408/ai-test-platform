from pydantic import BaseModel, Field, AliasChoices, ConfigDict
from app.core.utils import new_id, utc_now

class Project(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str = Field(default_factory=lambda: new_id("proj"))
    orgId: str = Field(default="", validation_alias=AliasChoices("orgId", "org_id"))
    name: str
    description: str = ""
    createdAt: str = Field(default_factory=utc_now, validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: str = Field(default_factory=utc_now, validation_alias=AliasChoices("updatedAt", "updated_at"))

class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""

class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)

class ProjectListResponse(BaseModel):
    items: list[Project]
    total: int
    page: int
    pageSize: int
    hasNext: bool

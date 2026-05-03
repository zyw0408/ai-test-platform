from pydantic import BaseModel, Field
from app.core.utils import utc_now

class OrganizationPublic(BaseModel):
    id: str
    name: str = ""
    slug: str | None = None
    createdAt: str = Field(default_factory=utc_now)

class TeamPublic(BaseModel):
    id: str
    orgId: str
    name: str = ""
    createdAt: str = Field(default_factory=utc_now)

class TeamInfo(TeamPublic):
    memberCount: int = 0

class TeamMemberPublic(BaseModel):
    id: str
    userId: str
    username: str = ""
    name: str = ""
    teamId: str | None = None
    role: str = "member"
    createdAt: str = Field(default_factory=utc_now)

class OrgCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    slug: str | None = Field(default=None, max_length=64)

class OrgUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    slug: str | None = Field(default=None, max_length=64)

class TeamCreateRequest(BaseModel):
    orgId: str
    name: str = Field(min_length=1, max_length=128)

class TeamUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)

class TeamMemberAddRequest(BaseModel):
    userId: str
    role: str = "member"

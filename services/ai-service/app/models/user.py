from pydantic import BaseModel, Field, AliasChoices, ConfigDict
from .base import UserRole

class UserPublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    username: str
    email: str | None = None
    phone: str | None = None
    name: str = ""
    nickname: str | None = None
    role: UserRole
    isActive: bool = Field(default=True, validation_alias=AliasChoices("isActive", "is_active"))
    avatarUrl: str | None = Field(default=None, validation_alias=AliasChoices("avatarUrl", "avatar_url"))
    wechatBound: bool = Field(default=False, validation_alias=AliasChoices("wechatBound", "wechat_bound"))
    createdAt: str = Field(validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: str = Field(validation_alias=AliasChoices("updatedAt", "updated_at"))
    lastLoginAt: str | None = Field(default=None, validation_alias=AliasChoices("lastLoginAt", "last_login_at"))

class UserAISettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    theme: str = "light"
    aiModel: str = Field(default="gpt-4o", validation_alias=AliasChoices("aiModel", "ai_model"))
    aiEndpoint: str = Field(default="", validation_alias=AliasChoices("aiEndpoint", "ai_endpoint"))
    aiKey: str = Field(default="", validation_alias=AliasChoices("aiKey", "ai_key"))
    aiTemperature: float = Field(default=0.7, validation_alias=AliasChoices("aiTemperature", "ai_temperature"))
    aiMaxTokens: int = Field(default=4096, validation_alias=AliasChoices("aiMaxTokens", "ai_max_tokens"))
    aiSystemPrompt: str = Field(default="", validation_alias=AliasChoices("aiSystemPrompt", "ai_system_prompt"))
    mcpServers: list[dict] = Field(default_factory=list, validation_alias=AliasChoices("mcpServers", "mcp_servers"))
    customRules: list[str] = Field(default_factory=list, validation_alias=AliasChoices("customRules", "custom_rules"))
    skillSearchPaths: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("skillSearchPaths", "skill_search_paths"),
    )
    
class SettingsUpdateRequest(BaseModel):
    settings: UserAISettings

class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str | None = None
    nickname: str | None = None
    email: str | None = None
    phone: str | None = None
    avatarUrl: str | None = Field(default=None, validation_alias=AliasChoices("avatarUrl", "avatar_url"))

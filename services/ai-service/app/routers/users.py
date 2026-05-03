from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Any, List
from .deps import get_current_user, get_user_auth, get_auth_session, get_db, get_ai_chat
from ..models import UserPublic, UserUpdateRequest, UserAISettings, SettingsUpdateRequest, UserRole, utc_now
from app.services.ai_chat import AIChatService

# This router handles user profile and settings, decoupled from authentication logic
router = APIRouter(prefix="", tags=["users"])


class UserRegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    phone: str | None = Field(default=None, min_length=6, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    role: UserRole = "tester"
    nickname: str | None = Field(default=None, min_length=1, max_length=64)
    avatarUrl: str | None = Field(default=None, max_length=512)


class UserPatchRequest(BaseModel):
    name: str | None = None
    nickname: str | None = None
    phone: str | None = None
    avatarUrl: str | None = None
    role: UserRole | None = None
    isActive: bool | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)


class WechatBindRequest(BaseModel):
    openId: str = Field(min_length=1)
    unionId: str | None = None
    nickname: str | None = None
    avatarUrl: str | None = None

@router.get("/users/me", response_model=UserPublic)
async def get_detailed_me(current_user: dict = Depends(get_current_user)) -> UserPublic:
    """Returns detailed profile for the current user"""
    # Simply mapping the current_user dict from session to UserPublic
    return UserPublic.model_validate(current_user)

@router.get("/settings", response_model=UserAISettings)
async def get_user_settings(
    current_user: dict = Depends(get_current_user),
    user_service = Depends(get_user_auth)
) -> UserAISettings:
    """Retrieves AI and system settings for the current user"""
    user_id = current_user["id"]
    settings_dict = user_service.get_user_settings(user_id)
    return UserAISettings.model_validate(settings_dict)

@router.post("/settings", response_model=UserAISettings)
async def update_user_settings(
    payload: SettingsUpdateRequest,
    current_user: dict = Depends(get_current_user),
    user_service = Depends(get_user_auth)
) -> UserAISettings:
    """Persists updated AI and system settings"""
    user_id = current_user["id"]
    user_service.update_user_settings(user_id, payload.settings.model_dump())
    return payload.settings

@router.post("/settings/test-model")
async def test_model_connection(
    payload: dict[str, Any],
    current_user: dict = Depends(get_current_user),
    user_service = Depends(get_user_auth),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    """Test whether model endpoint/api key/model can be reached with current (or draft) settings."""
    user_id = current_user["id"]
    persisted_settings = user_service.get_user_settings(user_id)
    draft_settings = payload.get("settings")
    merged = dict(persisted_settings or {})
    if isinstance(draft_settings, dict):
        merged.update(draft_settings)
    result = await ai_chat.test_connection(merged)
    return {
        **result,
        "checkedAt": utc_now(),
    }

@router.post("/settings/models")
async def discover_model_list(
    payload: dict[str, Any],
    current_user: dict = Depends(get_current_user),
    user_service = Depends(get_user_auth),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    """Discover available models from configured provider."""
    user_id = current_user["id"]
    persisted_settings = user_service.get_user_settings(user_id)
    draft_settings = payload.get("settings")
    merged = dict(persisted_settings or {})
    if isinstance(draft_settings, dict):
        merged.update(draft_settings)
    result = await ai_chat.discover_models(merged)
    return {
        **result,
        "checkedAt": utc_now(),
    }

@router.put("/auth/profile", response_model=UserPublic)
async def update_profile_alias(
    payload: UserUpdateRequest,
    current_user: dict = Depends(get_current_user),
    user_service = Depends(get_user_auth),
    auth_session = Depends(get_auth_session),
) -> UserPublic:
    """Updates user core profile information (nickname, name, etc.)"""
    # The frontend calls /api/auth/profile, so we host it here for decoupling
    updated = user_service.update_user(
        current_user["id"], 
        nickname=payload.nickname, 
        name=payload.name, 
        avatar_url=payload.avatarUrl
    )
    # Refresh cache for next /auth/me call
    auth_session.cache_user(updated)
    return UserPublic.model_validate(updated)

@router.get("/users", response_model=List[UserPublic])
async def admin_list_users(
    user_service = Depends(get_user_auth),
    current_user: dict = Depends(get_current_user)
) -> List[UserPublic]:
    """Admin-only route to list all platform users"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return [UserPublic.model_validate(item) for item in user_service.list_users()]


@router.post("/users/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def admin_register_user(
    payload: UserRegisterRequest,
    user_service=Depends(get_user_auth),
    current_user: dict = Depends(get_current_user),
) -> UserPublic:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    try:
        created = user_service.create_user(
            username=payload.username,
            password=payload.password,
            phone=payload.phone,
            name=payload.name,
            nickname=payload.nickname,
            avatar_url=payload.avatarUrl,
            role=payload.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return UserPublic.model_validate(created)


@router.patch("/users/{user_id}", response_model=UserPublic)
async def patch_user(
    user_id: str,
    payload: UserPatchRequest,
    user_service=Depends(get_user_auth),
    current_user: dict = Depends(get_current_user),
    auth_session = Depends(get_auth_session),
) -> UserPublic:
    is_admin = current_user["role"] == "admin"
    is_self = current_user["id"] == user_id
    if not is_admin and not is_self:
        raise HTTPException(status_code=403, detail="仅可修改自己的信息")
    if not is_admin and any(
        value is not None
        for value in [payload.role, payload.isActive, payload.password]
    ):
        raise HTTPException(status_code=403, detail="当前角色无权修改该字段")

    try:
        updated = user_service.update_user(
            user_id,
            password=payload.password if is_admin else None,
            phone=payload.phone,
            name=payload.name,
            nickname=payload.nickname,
            avatar_url=payload.avatarUrl,
            role=payload.role if is_admin else None,
            is_active=payload.isActive if is_admin else None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="用户不存在")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if is_self:
        auth_session.cache_user(updated)
    return UserPublic.model_validate(updated)


@router.post("/users/me/wechat/bind", response_model=UserPublic)
async def bind_wechat_for_me(
    payload: WechatBindRequest,
    current_user: dict = Depends(get_current_user),
    user_service=Depends(get_user_auth),
    auth_session = Depends(get_auth_session),
) -> UserPublic:
    try:
        updated = user_service.bind_wechat(
            user_id=current_user["id"],
            open_id=payload.openId,
            union_id=payload.unionId,
            nickname=payload.nickname,
            avatar_url=payload.avatarUrl,
            profile=None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="用户不存在")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    auth_session.cache_user(updated)
    return UserPublic.model_validate(updated)

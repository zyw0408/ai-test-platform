from pydantic import BaseModel, Field
from typing import Any
from .base import AuthMethod, UserRole

class LoginRequest(BaseModel):
    method: AuthMethod
    username: str | None = None
    password: str | None = None
    phone: str | None = None
    code: str | None = None
    wechatCode: str | None = None
    wechatOpenId: str | None = None
    wechatUnionId: str | None = None
    wechatNickname: str | None = None
    wechatAvatarUrl: str | None = None

class RegisterSmsCodeRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=32)

class RegisterPasswordRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    code: str = Field(min_length=4, max_length=16)
    password: str = Field(min_length=6, max_length=128)
    username: str | None = Field(default=None, min_length=3, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=64)
    nickname: str | None = Field(default=None, min_length=1, max_length=64)
    avatarUrl: str | None = Field(default=None, max_length=512)

class LoginUser(BaseModel):
    id: str
    username: str
    phone: str | None = None
    name: str
    nickname: str | None = None
    avatarUrl: str | None = None
    wechatBound: bool = False
    role: UserRole
    activeOrgId: str | None = None

class LoginData(BaseModel):
    token: str
    user: LoginUser

class LoginResponse(BaseModel):
    code: int = 0
    message: str
    data: LoginData

class LoginRiskUnlockRequest(BaseModel):
    phone: str
    code: str
    token: str | None = None

class RegisterWechatRequest(BaseModel):
    code: str = Field(min_length=1)
    state: str | None = None
    nickname: str | None = None
    avatarUrl: str | None = None

class ChangePasswordRequest(BaseModel):
    oldPassword: str = Field(min_length=6, max_length=128)
    newPassword: str = Field(min_length=6, max_length=128)

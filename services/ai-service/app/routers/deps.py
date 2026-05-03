from fastapi import Request, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.config import get_settings, Settings
from app.security import TokenError, decode_access_token
from app.services.user_auth import UserAuthService
from app.services.auth_session import AuthSessionService
from app.services.registration import RegistrationService
from app.services.login_risk import LoginRiskService
from app.services.wechat_oauth import WechatOAuthService
from app.services.wechat_register_state import WechatRegisterStateService
from app.services.audit import AuditService
from app.services.api_testing import ApiTestingService
from app.services.requirement_analysis import RequirementAnalysisService
from app.services.analysis_queue import AnalysisQueueService
from app.services.performance_testing import PerformanceTestingService
from app.services.security_testing import SecurityTestingService
from app.services.security_finding import SecurityFindingService
from app.services.ai_chat import AIChatService
from app.services.smithery import SmitheryService
from app.services.ui_locator import UiLocatorService
from app.services.lock import LockService
from app.services.vector_rag import VectorRAGService
from app.services.projects import ProjectService
from app.services.teams import TeamService
from app.store import JsonStore
from app.database import MultiTenantDB
from typing import Any

bearer_scheme = HTTPBearer(auto_error=False)

def get_db(request: Request) -> MultiTenantDB:
    return request.app.state.db

def get_store(request: Request) -> JsonStore:
    return request.app.state.store

def get_user_auth(request: Request) -> UserAuthService:
    return request.app.state.user_auth

def get_auth_session(request: Request) -> AuthSessionService:
    return request.app.state.auth_session

def get_registration(request: Request) -> RegistrationService:
    return request.app.state.registration

def get_login_risk(request: Request) -> LoginRiskService:
    return request.app.state.login_risk

def get_audit(request: Request) -> AuditService:
    return request.app.state.audit

def get_wechat_oauth(request: Request) -> WechatOAuthService:
    return request.app.state.wechat_oauth

def get_wechat_register_state(request: Request) -> WechatRegisterStateService:
    return request.app.state.wechat_register_state

def get_ai_chat(request: Request) -> AIChatService:
    return request.app.state.ai_chat

def get_smithery(request: Request) -> SmitheryService:
    return request.app.state.smithery

def get_ui_locator(request: Request) -> UiLocatorService:
    return request.app.state.ui_locator

def get_lock_service(request: Request) -> LockService:
    return request.app.state.lock

def get_projects(request: Request) -> ProjectService:
    return request.app.state.projects

def get_teams(request: Request) -> TeamService:
    return request.app.state.teams

def get_api_testing(request: Request) -> ApiTestingService:
    return request.app.state.api_testing

def get_test_cases(request: Request) -> Any:
    return request.app.state.test_cases

def get_test_runs(request: Request) -> Any:
    return request.app.state.test_runs

def get_performance_testing(request: Request) -> PerformanceTestingService:
    return request.app.state.performance_testing

def get_security_testing(request: Request) -> SecurityTestingService:
    return request.app.state.security_testing

def get_security_finding(request: Request) -> SecurityFindingService:
    return request.app.state.security_finding

def get_requirement_analysis(request: Request) -> RequirementAnalysisService:
    return request.app.state.requirement_analysis

def get_vector_rag(request: Request) -> VectorRAGService:
    return request.app.state.vector_rag

def get_analysis_queue(request: Request) -> AnalysisQueueService:
    return request.app.state.analysis_queue

def get_automation(request: Request) -> Any:
    return request.app.state.automation

def get_reporting(request: Request) -> Any:
    return request.app.state.reporting

def get_current_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    token = None
    if credentials:
        token = credentials.credentials
    else:
        # Fallback to cookie for Next.js proxy/client calls
        token = request.cookies.get("ai_test_token")

    if not token:
        raise HTTPException(status_code=401, detail="缺少 Authorization Bearer Token")

    settings = request.app.state.settings
    try:
        payload = decode_access_token(token, settings.auth_secret)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user_id = payload["sub"]
    token_id = payload["jti"]
    auth_session = get_auth_session(request)
    if not auth_session.is_token_active(token_id, user_id):
        raise HTTPException(status_code=401, detail="登录态已失效，请重新登录")

    user = auth_session.get_cached_user(user_id) or get_user_auth(request).get_user_by_id(user_id)
    if not user:
        auth_session.revoke_token(token_id)
        raise HTTPException(status_code=401, detail="登录态无效，用户不存在")
    if not user["isActive"]:
        auth_session.revoke_token(token_id)
        raise HTTPException(status_code=403, detail="当前用户已禁用")
    auth_session.cache_user(user)
    return {"user": user, "tokenId": token_id, "payload": payload}

def get_current_user(auth_context: dict[str, Any] = Depends(get_current_auth)) -> dict:
    return auth_context["user"]

def require_roles(*allowed_roles: str):
    allowed = set(allowed_roles)
    def _dependency(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role"] not in allowed:
            raise HTTPException(status_code=403, detail="当前角色无权限执行此操作")
        return current_user
    return _dependency

def get_user_org_ids(
    current_user: dict = Depends(get_current_user),
    team_service: TeamService = Depends(get_teams)
) -> list[str]:
    """Dependency that returns the organization IDs the current user belongs to."""
    ids = team_service.get_user_org_ids(current_user["id"])
    if not ids:
        return ["DEFAULT_ORG"]
    return ids

def get_admin_user(current_user: dict = Depends(require_roles("admin"))) -> dict:
    return current_user

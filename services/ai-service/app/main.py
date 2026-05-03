from __future__ import annotations
from contextlib import asynccontextmanager
import logging
import time
import asyncio
from typing import Any
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPBearer

from app.cache import build_cache
from app.config import get_settings
from app.database import build_database, SQLiteDatabase
from app.store import JsonStore
from app.services.sms_provider import build_sms_provider
from app.services.user_auth import UserAuthService
from app.services.auth_session import AuthSessionService
from app.services.login_risk import LoginRiskService
from app.services.registration import RegistrationService
from app.services.wechat_oauth import WechatOAuthService
from app.services.wechat_register_state import WechatRegisterStateService
from app.services.audit import AuditService
from app.services.api_testing import ApiTestingService
from app.services.requirement_analysis import RequirementAnalysisService
from app.services.analysis_queue import AnalysisQueueService
from app.services.performance_testing import PerformanceTestingService
from app.services.ai_chat import AIChatService
from app.services.smithery import SmitheryService
from app.services.ui_locator import UiLocatorService
from app.services.lock import LockService
from app.services.vector_rag import VectorRAGService
from app.services.projects import ProjectService
from app.services.teams import TeamService
from app.repositories.project_repo import ProjectRepository
from app.repositories.team_repo import TeamRepository
from app.repositories.user_repo import UserRepository
from app.repositories.requirement_repo import RequirementRepository
from app.repositories.ai_operation_repo import AiOperationRepository
from app.repositories.case_repo import TestCaseRepository
from app.repositories.run_repo import TestRunRepository
from app.services.providers import build_provider
from app.models import utc_now

# Correct explicit imports for routers
from app.routers.auth import router as auth_router
from app.routers.teams import router as teams_router
from app.routers.ai import router as ai_router
from app.routers.requirements import router as req_router
from app.routers.testing import router as test_router, runs_router
from app.routers.users import router as users_router
from app.routers.integrations import router as int_router
from app.routers.projects import router as proj_router
from app.routers.cases import router as cases_router
from app.routers.reports import router as reports_router
from app.routers.specs import router as specs_router
from app.routers.security import router as security_router
from app.services.security_finding import SecurityFindingService

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    
    # Foundational services
    print("Lifespan: Loading database...")
    app.state.db = build_database(settings)
    app.state.db.init_schema()
    print("Lifespan: Loading cache...")
    app.state.cache = build_cache(settings)
    print("Lifespan: Loading store...")
    app.state.store = JsonStore(settings.storage_dir, db=app.state.db)
    
    # Repositories
    print("Lifespan: Loading repositories...")
    user_repo = UserRepository(app.state.db)
    project_repo = ProjectRepository(app.state.db)
    team_repo = TeamRepository(app.state.db)
    requirement_repo = RequirementRepository(app.state.db)
    ai_op_repo = AiOperationRepository(app.state.db)
    case_repo = TestCaseRepository(app.state.db)
    run_repo = TestRunRepository(app.state.store)
    
    # AI Provider
    provider = build_provider(settings)
    app.state.provider = provider

    # Application Services
    app.state.user_auth = UserAuthService(app.state.db, settings, user_repo)
    app.state.user_auth.ensure_default_admin()
    app.state.auth_session = AuthSessionService(app.state.cache)
    app.state.login_risk = LoginRiskService(app.state.cache, settings)
    
    sms_provider = build_sms_provider(settings)
    app.state.registration = RegistrationService(
        cache=app.state.cache, settings=settings, sms_provider=sms_provider
    )
    
    app.state.projects = ProjectService(project_repo)
    app.state.teams = TeamService(team_repo)
    app.state.wechat_oauth = WechatOAuthService(settings)
    app.state.wechat_register_state = WechatRegisterStateService(app.state.cache, settings)
    
    app.state.audit = AuditService(app.state.db)
    app.state.api_testing = ApiTestingService(app.state.db)
    
    app.state.requirement_analysis = RequirementAnalysisService(
        db=app.state.db,
        cache=app.state.cache,
        provider=provider,
        settings=settings,
        requirement_repo=requirement_repo,
        ai_op_repo=ai_op_repo,
        user_repo=user_repo,
    )
    
    app.state.smithery = SmitheryService(settings)
    app.state.ui_locator = UiLocatorService(settings)
    app.state.lock = LockService(app.state.cache)
    app.state.vector_rag = VectorRAGService(db=app.state.db, settings=settings)
    
    app.state.analysis_queue = AnalysisQueueService(settings)
    app.state.performance_testing = PerformanceTestingService(
        api_testing_service=app.state.api_testing,
        store=app.state.store,
        artifacts_dir=settings.artifacts_dir,
        max_concurrent_runs=settings.performance_max_concurrent_runs,
        max_queue_size=settings.performance_max_queue_size,
        project_max_concurrent_runs=settings.performance_project_max_concurrent_runs,
        project_max_queue_size=settings.performance_project_max_queue_size,
        regression_max_p95_delta_ms=settings.performance_regression_max_p95_delta_ms,
        regression_max_error_rate_delta=settings.performance_regression_max_error_rate_delta,
        regression_min_tps_delta=settings.performance_regression_min_tps_delta,
    )
    from app.services.security_testing import SecurityTestingService
    app.state.security_testing = SecurityTestingService(
        api_testing_service=app.state.api_testing
    )
    app.state.security_finding = SecurityFindingService(app.state.db)
    app.state.ai_chat = AIChatService(
        db=app.state.db,
        api_testing=app.state.api_testing,
        performance_testing=app.state.performance_testing,
        security_testing=app.state.security_testing,
        smithery=app.state.smithery,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        model=settings.model_name,
        max_tokens=settings.model_max_tokens,
        temperature=settings.model_temperature,
    )

    from app.services.testing import TestCaseService
    from app.services.test_runs import TestRunService
    from app.services.automation import AutomationService
    from app.services.reporting import ReportingService

    app.state.test_cases = TestCaseService(case_repo)
    app.state.test_runs = TestRunService(run_repo)
    
    app.state.automation = AutomationService(
        run_repo=run_repo,
        artifacts_dir=settings.artifacts_dir,
        node_bin=settings.node_bin,
        ui_runner_dir=settings.ui_runner_dir,
        ui_runner_timeout_seconds=settings.ui_runner_timeout_seconds
    )
    app.state.reporting = ReportingService(run_repo, case_repo, app.state.store)

    yield
    
    # Cleanup
    for attr in ["performance_testing", "api_testing"]:
        if hasattr(app.state, attr):
            obj = getattr(app.state, attr)
            if hasattr(obj, "aclose"):
                try:
                    await obj.aclose()
                except Exception:
                    pass

    # Generic cleanup for everything else
    for attr in ["db", "cache", "store"]:
        if hasattr(app.state, attr):
            obj = getattr(app.state, attr)
            if hasattr(obj, "close"):
                try:
                    res = obj.close()
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    pass
            elif hasattr(obj, "aclose"):
                try:
                    await obj.aclose()
                except Exception:
                    pass

app = FastAPI(title="AI Test Platform API", lifespan=lifespan)

# CORS
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

# Timing Middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = time.perf_counter() - start_time
    response.headers["X-Process-Time-Ms"] = str(int(process_time * 1000))
    return response

# Register Routers
app.include_router(auth_router)
app.include_router(teams_router)
app.include_router(ai_router)
app.include_router(req_router)
app.include_router(test_router)
app.include_router(runs_router)
app.include_router(users_router)
app.include_router(int_router)
app.include_router(proj_router)
app.include_router(cases_router)
app.include_router(reports_router)
app.include_router(specs_router)
app.include_router(security_router)

@app.get("/")
async def root():
    return {"status": "ok", "message": "AI Test Platform API is running"}

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": utc_now()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

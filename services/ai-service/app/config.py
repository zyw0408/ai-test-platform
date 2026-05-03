from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_DEFAULT_DOCKER_PG_URL = "postgresql://ai_test:ai_test_123456@127.0.0.1:5433/ai_test_platform"


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_key = key.strip()
        if not env_key or env_key in os.environ:
            continue
        env_value = value.strip()
        if len(env_value) >= 2 and env_value[0] == env_value[-1] and env_value[0] in {'"', "'"}:
            env_value = env_value[1:-1]
        os.environ[env_key] = env_value


def _load_local_env_files(service_root: Path) -> None:
    repo_root = service_root.parents[1]
    _load_env_file(service_root / ".env")
    _load_env_file(repo_root / ".env")


@dataclass(slots=True)
class Settings:
    storage_dir: Path
    artifacts_dir: Path
    db_path: Path
    node_bin: str
    ui_runner_dir: Path
    ui_runner_timeout_seconds: int
    database_url: str | None
    database_connect_timeout_seconds: int
    database_fallback_to_sqlite_on_error: bool
    model_provider: str
    model_base_url: str | None
    model_name: str
    model_api_key: str | None
    model_max_tokens: int
    model_temperature: float
    smithery_bin: str
    smithery_namespace: str | None
    auth_secret: str
    auth_access_token_minutes: int
    default_admin_username: str
    default_admin_password: str
    default_admin_name: str
    default_admin_phone: str | None
    sms_login_code: str
    sms_provider: str
    sms_aliyun_access_key_id: str | None
    sms_aliyun_access_key_secret: str | None
    sms_aliyun_sign_name: str | None
    sms_aliyun_template_code: str | None
    sms_aliyun_template_param_key: str
    sms_aliyun_endpoint: str
    redis_enabled: bool
    redis_url: str
    redis_prefix: str
    cache_default_ttl_seconds: int
    privacy_hash_secret: str
    privacy_fernet_key: str | None
    wechat_oauth_enabled: bool
    wechat_app_id: str | None
    wechat_app_secret: str | None
    wechat_http_timeout_seconds: float
    wechat_register_state_ttl_seconds: int
    wechat_oauth_allowed_redirect_hosts: list[str]
    wechat_oauth_allowed_next_prefixes: list[str]
    login_fail_limit: int
    login_fail_window_seconds: int
    login_lock_seconds: int
    register_sms_code_ttl_seconds: int
    register_sms_cooldown_seconds: int
    register_sms_daily_limit: int
    cors_allow_origins: list[str]
    cors_allow_methods: list[str]
    cors_allow_headers: list[str]
    cors_expose_headers: list[str]
    cors_allow_credentials: bool
    request_id_header: str
    analysis_worker_enabled: bool
    performance_max_concurrent_runs: int
    performance_max_queue_size: int
    performance_project_max_concurrent_runs: int
    performance_project_max_queue_size: int
    performance_regression_max_p95_delta_ms: float
    performance_regression_max_error_rate_delta: float
    performance_regression_min_tps_delta: float
    vector_enabled: bool
    vector_backend: str
    vector_index_name: str
    vector_prefix: str
    vector_field: str
    vector_dim: int
    vector_distance: str
    vector_top_k: int
    vector_max_context_chunks: int
    vector_embedding_model: str | None
    vector_embedding_base_url: str | None
    vector_embedding_api_key: str | None


def get_settings() -> Settings:
    service_root = Path(__file__).resolve().parents[1]
    _load_local_env_files(service_root)
    repo_root = service_root.parents[1]
    default_storage_dir = service_root / "data"
    storage_dir = Path(
        os.getenv("AI_SERVICE_STORAGE_DIR", str(default_storage_dir))
    ).resolve()
    artifacts_dir = Path(
        os.getenv(
            "AI_SERVICE_ARTIFACTS_DIR",
            str(storage_dir / "artifacts"),
        )
    ).resolve()
    db_path = Path(
        os.getenv("AI_SERVICE_DB_PATH", str(storage_dir / "platform.db"))
    ).resolve()

    auth_secret = os.getenv("AI_SERVICE_AUTH_SECRET", "replace-me-in-prod")
    raw_database_url = os.getenv("AI_SERVICE_DATABASE_URL")
    if raw_database_url is None:
        database_url = _DEFAULT_DOCKER_PG_URL
    else:
        text = raw_database_url.strip()
        database_url = text or None

    return Settings(
        storage_dir=storage_dir,
        artifacts_dir=artifacts_dir,
        db_path=db_path,
        node_bin=os.getenv("AI_SERVICE_NODE_BIN", "node"),
        ui_runner_dir=Path(
            os.getenv(
                "AI_SERVICE_UI_RUNNER_DIR",
                str(repo_root / "workers" / "ui-runner"),
            )
        ).resolve(),
        ui_runner_timeout_seconds=int(
            os.getenv("AI_SERVICE_UI_RUNNER_TIMEOUT_SECONDS", "180")
        ),
        database_url=database_url,
        database_connect_timeout_seconds=int(
            os.getenv("AI_SERVICE_DATABASE_CONNECT_TIMEOUT_SECONDS", "3")
        ),
        database_fallback_to_sqlite_on_error=_env_bool(
            "AI_SERVICE_DATABASE_FALLBACK_TO_SQLITE_ON_ERROR",
            True,
        ),
        model_provider=os.getenv("AI_SERVICE_MODEL_PROVIDER", "openai-compatible"),
        model_base_url=os.getenv("AI_SERVICE_MODEL_BASE_URL", "https://api.deepseek.com/v1"),
        model_name=os.getenv("AI_SERVICE_MODEL_NAME", "deepseek-chat"),
        model_api_key=os.getenv("AI_SERVICE_MODEL_API_KEY", ""),
        model_max_tokens=int(os.getenv("AI_SERVICE_MODEL_MAX_TOKENS", "4096")),
        model_temperature=float(os.getenv("AI_SERVICE_MODEL_TEMPERATURE", "0.7")),
        smithery_bin=os.getenv("AI_SERVICE_SMITHERY_BIN", "smithery"),
        smithery_namespace=os.getenv("AI_SERVICE_SMITHERY_NAMESPACE") or None,
        auth_secret=auth_secret,
        auth_access_token_minutes=int(
            os.getenv("AI_SERVICE_AUTH_ACCESS_TOKEN_MINUTES", "720")
        ),
        default_admin_username=os.getenv("AI_SERVICE_DEFAULT_ADMIN_USERNAME", "admin"),
        default_admin_password=os.getenv("AI_SERVICE_DEFAULT_ADMIN_PASSWORD", "123456"),
        default_admin_name=os.getenv("AI_SERVICE_DEFAULT_ADMIN_NAME", "超级管理员"),
        default_admin_phone=os.getenv("AI_SERVICE_DEFAULT_ADMIN_PHONE") or None,
        sms_login_code=os.getenv("AI_SERVICE_SMS_LOGIN_CODE", "123456"),
        sms_provider=os.getenv("AI_SERVICE_SMS_PROVIDER", "mock"),
        sms_aliyun_access_key_id=os.getenv("AI_SERVICE_SMS_ALIYUN_ACCESS_KEY_ID") or None,
        sms_aliyun_access_key_secret=os.getenv("AI_SERVICE_SMS_ALIYUN_ACCESS_KEY_SECRET") or None,
        sms_aliyun_sign_name=os.getenv("AI_SERVICE_SMS_ALIYUN_SIGN_NAME") or None,
        sms_aliyun_template_code=os.getenv("AI_SERVICE_SMS_ALIYUN_TEMPLATE_CODE") or None,
        sms_aliyun_template_param_key=os.getenv(
            "AI_SERVICE_SMS_ALIYUN_TEMPLATE_PARAM_KEY",
            "code",
        ),
        sms_aliyun_endpoint=os.getenv(
            "AI_SERVICE_SMS_ALIYUN_ENDPOINT",
            "dysmsapi.aliyuncs.com",
        ),
        redis_enabled=os.getenv("AI_SERVICE_REDIS_ENABLED", "true").lower() not in {"0", "false", "no"},
        redis_url=os.getenv("AI_SERVICE_REDIS_URL", "redis://127.0.0.1:6380/0"),
        redis_prefix=os.getenv("AI_SERVICE_REDIS_PREFIX", "ai-test:"),
        cache_default_ttl_seconds=int(
            os.getenv("AI_SERVICE_CACHE_DEFAULT_TTL_SECONDS", "120")
        ),
        privacy_hash_secret=os.getenv("AI_SERVICE_PRIVACY_HASH_SECRET", auth_secret),
        privacy_fernet_key=os.getenv("AI_SERVICE_PRIVACY_FERNET_KEY") or None,
        wechat_oauth_enabled=os.getenv("AI_SERVICE_WECHAT_OAUTH_ENABLED", "false").lower()
        in {"1", "true", "yes"},
        wechat_app_id=os.getenv("AI_SERVICE_WECHAT_APP_ID") or None,
        wechat_app_secret=os.getenv("AI_SERVICE_WECHAT_APP_SECRET") or None,
        wechat_http_timeout_seconds=float(
            os.getenv("AI_SERVICE_WECHAT_HTTP_TIMEOUT_SECONDS", "5")
        ),
        wechat_register_state_ttl_seconds=int(
            os.getenv("AI_SERVICE_WECHAT_REGISTER_STATE_TTL_SECONDS", "300")
        ),
        wechat_oauth_allowed_redirect_hosts=_split_csv(
            os.getenv(
                "AI_SERVICE_WECHAT_OAUTH_ALLOWED_REDIRECT_HOSTS",
                "127.0.0.1,localhost",
            )
        )
        or ["127.0.0.1", "localhost"],
        wechat_oauth_allowed_next_prefixes=_split_csv(
            os.getenv(
                "AI_SERVICE_WECHAT_OAUTH_ALLOWED_NEXT_PREFIXES",
                "/,/projects,/cases,/reports,/security,/performance,/auto-tests,/api-tests,/runs",
            )
        )
        or [
            "/",
            "/projects",
            "/cases",
            "/reports",
            "/security",
            "/performance",
            "/auto-tests",
            "/api-tests",
            "/runs",
        ],
        login_fail_limit=int(os.getenv("AI_SERVICE_LOGIN_FAIL_LIMIT", "5")),
        login_fail_window_seconds=int(
            os.getenv("AI_SERVICE_LOGIN_FAIL_WINDOW_SECONDS", "600")
        ),
        login_lock_seconds=int(os.getenv("AI_SERVICE_LOGIN_LOCK_SECONDS", "900")),
        register_sms_code_ttl_seconds=int(
            os.getenv("AI_SERVICE_REGISTER_SMS_CODE_TTL_SECONDS", "300")
        ),
        register_sms_cooldown_seconds=int(
            os.getenv("AI_SERVICE_REGISTER_SMS_COOLDOWN_SECONDS", "60")
        ),
        register_sms_daily_limit=int(
            os.getenv("AI_SERVICE_REGISTER_SMS_DAILY_LIMIT", "10")
        ),
        cors_allow_origins=_split_csv(
            os.getenv(
                "AI_SERVICE_CORS_ALLOW_ORIGINS",
                "http://127.0.0.1:3000,http://localhost:3000",
            )
        )
        or ["http://127.0.0.1:3000", "http://localhost:3000"],
        cors_allow_methods=_split_csv(
            os.getenv(
                "AI_SERVICE_CORS_ALLOW_METHODS",
                "GET,POST,PUT,PATCH,DELETE,OPTIONS",
            )
        )
        or ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        cors_allow_headers=_split_csv(
            os.getenv(
                "AI_SERVICE_CORS_ALLOW_HEADERS",
                "Authorization,Content-Type,X-Request-Id",
            )
        )
        or ["Authorization", "Content-Type", "X-Request-Id"],
        cors_expose_headers=_split_csv(
            os.getenv(
                "AI_SERVICE_CORS_EXPOSE_HEADERS",
                "X-Request-Id,X-Process-Time-Ms",
            )
        )
        or ["X-Request-Id", "X-Process-Time-Ms"],
        cors_allow_credentials=_env_bool("AI_SERVICE_CORS_ALLOW_CREDENTIALS", True),
        request_id_header=os.getenv("AI_SERVICE_REQUEST_ID_HEADER", "X-Request-Id"),
        analysis_worker_enabled=_env_bool("AI_SERVICE_ANALYSIS_WORKER_ENABLED", True),
        performance_max_concurrent_runs=int(
            os.getenv("AI_SERVICE_PERFORMANCE_MAX_CONCURRENT_RUNS", "2")
        ),
        performance_max_queue_size=int(
            os.getenv("AI_SERVICE_PERFORMANCE_MAX_QUEUE_SIZE", "20")
        ),
        performance_project_max_concurrent_runs=int(
            os.getenv("AI_SERVICE_PERFORMANCE_PROJECT_MAX_CONCURRENT_RUNS", "1")
        ),
        performance_project_max_queue_size=int(
            os.getenv("AI_SERVICE_PERFORMANCE_PROJECT_MAX_QUEUE_SIZE", "5")
        ),
        performance_regression_max_p95_delta_ms=float(
            os.getenv("AI_SERVICE_PERFORMANCE_REGRESSION_MAX_P95_DELTA_MS", "100")
        ),
        performance_regression_max_error_rate_delta=float(
            os.getenv("AI_SERVICE_PERFORMANCE_REGRESSION_MAX_ERROR_RATE_DELTA", "0.02")
        ),
        performance_regression_min_tps_delta=float(
            os.getenv("AI_SERVICE_PERFORMANCE_REGRESSION_MIN_TPS_DELTA", "-5")
        ),
        vector_enabled=_env_bool("AI_SERVICE_VECTOR_ENABLED", True),
        vector_backend=os.getenv("AI_SERVICE_VECTOR_BACKEND", "sqlite"),
        vector_index_name=os.getenv("AI_SERVICE_VECTOR_INDEX_NAME", "vector_index"),
        vector_prefix=os.getenv("AI_SERVICE_VECTOR_PREFIX", "doc:"),
        vector_field=os.getenv("AI_SERVICE_VECTOR_FIELD", "vector"),
        vector_dim=int(os.getenv("AI_SERVICE_VECTOR_DIM", "1536")),
        vector_distance=os.getenv("AI_SERVICE_VECTOR_DISTANCE", "COSINE").upper(),
        vector_top_k=int(os.getenv("AI_SERVICE_VECTOR_TOP_K", "8")),
        vector_max_context_chunks=int(os.getenv("AI_SERVICE_VECTOR_MAX_CONTEXT_CHUNKS", "6")),
        vector_embedding_model=os.getenv("AI_SERVICE_VECTOR_EMBEDDING_MODEL") or None,
        vector_embedding_base_url=os.getenv("AI_SERVICE_VECTOR_EMBEDDING_BASE_URL") or None,
        vector_embedding_api_key=os.getenv("AI_SERVICE_VECTOR_EMBEDDING_API_KEY") or None,
    )

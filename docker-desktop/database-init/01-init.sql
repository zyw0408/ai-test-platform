CREATE SCHEMA IF NOT EXISTS platform AUTHORIZATION ai_test;

-- Healthcheck table (legacy compatibility)
CREATE TABLE IF NOT EXISTS platform.healthcheck (
  id SERIAL PRIMARY KEY,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO platform.healthcheck (status)
SELECT 'ok'
WHERE NOT EXISTS (
  SELECT 1 FROM platform.healthcheck
);

-- Generic entity storage for projects/specs/cases/runs/artifacts
CREATE TABLE IF NOT EXISTS public.entities (
  collection TEXT NOT NULL,
  id TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT,
  PRIMARY KEY (collection, id)
);

CREATE INDEX IF NOT EXISTS idx_entities_collection_created
ON public.entities(collection, created_at);

CREATE INDEX IF NOT EXISTS idx_entities_collection_deleted_updated
ON public.entities(collection, deleted_at, updated_at DESC, id ASC);

CREATE INDEX IF NOT EXISTS idx_entities_collection_deleted_created
ON public.entities(collection, deleted_at, created_at DESC, id ASC);

CREATE INDEX IF NOT EXISTS idx_entities_cases_project_kind_updated
ON public.entities(
  collection,
  deleted_at,
  ((payload::jsonb ->> 'projectId')),
  ((payload::jsonb ->> 'kind')),
  updated_at DESC,
  id ASC
);

CREATE INDEX IF NOT EXISTS idx_entities_cases_spec_updated
ON public.entities(
  collection,
  deleted_at,
  ((payload::jsonb ->> 'specId')),
  updated_at DESC,
  id ASC
);

CREATE INDEX IF NOT EXISTS idx_entities_cases_kind_updated
ON public.entities(
  collection,
  deleted_at,
  ((payload::jsonb ->> 'kind')),
  updated_at DESC,
  id ASC
);

CREATE INDEX IF NOT EXISTS idx_entities_specs_project_created
ON public.entities(
  collection,
  deleted_at,
  ((payload::jsonb ->> 'projectId')),
  created_at ASC,
  id ASC
);

-- User/auth domain
CREATE TABLE IF NOT EXISTS public.users (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  phone TEXT UNIQUE,
  name TEXT NOT NULL,
  nickname TEXT,
  avatar_url TEXT,
  role TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS public.user_password_credentials (
  user_id TEXT PRIMARY KEY,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES public.users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.user_phone_identities (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL UNIQUE,
  phone_hash TEXT NOT NULL UNIQUE,
  phone_cipher TEXT,
  phone_last4 TEXT NOT NULL,
  verified_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES public.users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.user_wechat_accounts (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL UNIQUE,
  openid_hash TEXT NOT NULL UNIQUE,
  openid_cipher TEXT,
  unionid_hash TEXT UNIQUE,
  unionid_cipher TEXT,
  nickname TEXT,
  avatar_url TEXT,
  profile_cipher TEXT,
  last_bound_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES public.users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.user_login_events (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  method TEXT NOT NULL,
  success INTEGER NOT NULL,
  ip TEXT,
  user_agent TEXT,
  detail TEXT,
  created_at TEXT NOT NULL
);

-- Requirements/analysis domain
CREATE TABLE IF NOT EXISTS public.requirements (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  source_spec_id TEXT,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  tags_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'draft',
  latest_analysis_version INTEGER,
  created_by TEXT,
  deleted_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_requirements_project_created
ON public.requirements(project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_requirements_active_project_updated
ON public.requirements(project_id, deleted_at, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_requirements_active_status_updated
ON public.requirements(status, deleted_at, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_requirements_deleted_updated
ON public.requirements(deleted_at, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_requirements_project_status_updated
ON public.requirements(project_id, status, deleted_at, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_requirements_dedupe_ci
ON public.requirements(project_id, deleted_at, lower(title), lower(content));

CREATE INDEX IF NOT EXISTS idx_requirements_fts
ON public.requirements
USING GIN (
  to_tsvector(
    'simple',
    COALESCE(title, '') || ' ' || COALESCE(content, '') || ' ' || COALESCE(tags_json, '')
  )
);

CREATE TABLE IF NOT EXISTS public.requirement_analysis_versions (
  id TEXT PRIMARY KEY,
  requirement_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  analysis_json TEXT NOT NULL,
  ai_operation_id TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(requirement_id, version),
  FOREIGN KEY(requirement_id) REFERENCES public.requirements(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_req_analysis_requirement_created
ON public.requirement_analysis_versions(requirement_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.ai_operations (
  id TEXT PRIMARY KEY,
  operation_type TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  status TEXT NOT NULL,
  request_payload TEXT,
  response_payload TEXT,
  error_message TEXT,
  created_by TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_operations_target
ON public.ai_operations(target_type, target_id, created_at DESC);

-- API testing domain
CREATE TABLE IF NOT EXISTS public.api_collections (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  variables_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT,
  deleted_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_collections_project_updated
ON public.api_collections(project_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_api_collections_project_deleted_updated
ON public.api_collections(project_id, deleted_at, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.api_requests (
  id TEXT PRIMARY KEY,
  collection_id TEXT NOT NULL,
  parent_id TEXT,
  name TEXT NOT NULL,
  group_name TEXT NOT NULL DEFAULT 'default',
  tags_json TEXT NOT NULL DEFAULT '[]',
  method TEXT NOT NULL,
  url TEXT NOT NULL,
  query_json TEXT NOT NULL DEFAULT '[]',
  headers_json TEXT NOT NULL DEFAULT '[]',
  body_mode TEXT NOT NULL DEFAULT 'none',
  body_raw TEXT NOT NULL DEFAULT '',
  body_form_json TEXT NOT NULL DEFAULT '[]',
  auth_type TEXT NOT NULL DEFAULT 'none',
  auth_json TEXT NOT NULL DEFAULT '{}',
  tests_json TEXT NOT NULL DEFAULT '[]',
  pre_script TEXT NOT NULL DEFAULT '',
  test_script TEXT NOT NULL DEFAULT '',
  is_folder INTEGER NOT NULL DEFAULT 0,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_by TEXT,
  deleted_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_requests_collection_sort
ON public.api_requests(collection_id, sort_order ASC, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_api_requests_collection_deleted_sort
ON public.api_requests(collection_id, deleted_at, sort_order ASC, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_api_requests_collection_group
ON public.api_requests(collection_id, group_name, sort_order ASC);

CREATE TABLE IF NOT EXISTS public.api_environments (
  id TEXT PRIMARY KEY,
  collection_id TEXT NOT NULL,
  name TEXT NOT NULL,
  variables_json TEXT NOT NULL DEFAULT '{}',
  is_default INTEGER NOT NULL DEFAULT 0,
  created_by TEXT,
  deleted_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_env_collection_updated
ON public.api_environments(collection_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_api_env_collection_deleted_default_updated
ON public.api_environments(collection_id, deleted_at, is_default DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.api_request_runs (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  collection_id TEXT NOT NULL,
  method TEXT NOT NULL,
  url TEXT NOT NULL,
  status_code INTEGER,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  success INTEGER NOT NULL DEFAULT 0,
  response_headers_json TEXT NOT NULL DEFAULT '{}',
  response_body TEXT NOT NULL DEFAULT '',
  response_size INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  assertions_json TEXT NOT NULL DEFAULT '[]',
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_runs_collection_created
ON public.api_request_runs(collection_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_api_runs_request_created
ON public.api_request_runs(request_id, created_at DESC);

-- Audit domain
CREATE TABLE IF NOT EXISTS public.audit_logs (
  id TEXT PRIMARY KEY,
  actor_id TEXT,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  payload_json TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_target
ON public.audit_logs(target_type, target_id, created_at DESC);

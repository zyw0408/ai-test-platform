# AI Test Platform / AI+测试平台

## 中文说明

AI+测试平台是一套面向企业测试团队的 Docker 化测试工作台，覆盖项目、需求、用例、接口测试、自动化测试、性能测试、安全测试与报告等核心流程。

### 仓库内容

本仓库只保留部署和运行所需内容：

- `apps/web`：Next.js 前端应用
- `services/ai-service`：FastAPI 后端服务
- `services/test-platform-mcp`：AI 助手调用平台能力的 MCP 工具服务
- `workers/api-runner`：接口测试执行器
- `workers/ui-runner`：UI 自动化执行器
- `packages/shared-schema`：前后端共享协议与类型
- `docker-desktop`：Docker Compose、Nginx、PostgreSQL、Redis 与环境模板
- `scripts`：Docker 构建、启动、停止脚本

接口设计文档、开发环境缓存、本地数据库、真实环境变量和其他非交付文件不包含在仓库中。Docker 部署会包含 Web、后端 AI 服务、MCP 工具服务、API runner、UI runner、PostgreSQL、Redis 与 Nginx。

### 快速启动

1. 安装 Docker Desktop，并确认支持 `docker compose`。
2. 在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1
```

3. 打开：

```text
http://localhost
```

MCP 工具服务默认暴露在：

```text
http://localhost:8765/sse
```

### 常用命令

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-build.ps1
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1
powershell -ExecutionPolicy Bypass -File scripts/docker-down.ps1
```

如需强制重建前端与网关：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1 -NoCache -ForceRecreate -Services web nginx
```

### 环境变量

首次运行脚本时，如果 `docker-desktop/.env` 不存在，会自动从 `docker-desktop/.env.example` 生成。真实 `.env` 文件不会提交到仓库。

## English

AI Test Platform is a Dockerized testing workspace for enterprise QA teams. It covers project management, requirements, test cases, API testing, UI automation, performance testing, security testing, and reporting workflows.

### Repository Scope

This repository keeps only the files required for deployment and runtime:

- `apps/web`: Next.js web application
- `services/ai-service`: FastAPI backend service
- `services/test-platform-mcp`: MCP tool service used by the AI assistant
- `workers/api-runner`: API test runner
- `workers/ui-runner`: UI automation runner
- `packages/shared-schema`: shared contracts and types
- `docker-desktop`: Docker Compose, Nginx, PostgreSQL, Redis, and environment templates
- `scripts`: Docker build, start, and stop scripts

API design documents, local caches, local databases, real environment files, and other non-delivery artifacts are excluded. The Docker deployment includes the web app, backend AI service, MCP tool service, API runner, UI runner, PostgreSQL, Redis, and Nginx.

### Quick Start

1. Install Docker Desktop and make sure `docker compose` is available.
2. Run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1
```

3. Open:

```text
http://localhost
```

The MCP tool service is exposed at:

```text
http://localhost:8765/sse
```

### Useful Commands

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-build.ps1
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1
powershell -ExecutionPolicy Bypass -File scripts/docker-down.ps1
```

To rebuild the web app and gateway from scratch:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1 -NoCache -ForceRecreate -Services web nginx
```

### Environment

On first run, the scripts create `docker-desktop/.env` from `docker-desktop/.env.example` if it does not exist. Real `.env` files are not committed.

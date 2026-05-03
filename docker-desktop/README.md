# Docker Desktop 部署说明

本目录用于 Docker Desktop / Docker Compose 部署 AI+测试平台。适合需要完整服务编排的场景，包括前端、后端、数据库、缓存、反向代理和 MCP 工具服务。

## 服务组成

- `nginx`：统一入口与反向代理
- `web`：Next.js 前端控制台
- `api`：FastAPI 后端业务与 AI 服务，镜像内包含 API runner 与 UI runner
- `mcp`：AI 助手 MCP 工具桥，默认以 SSE 方式暴露平台工具
- `postgres`：业务数据库
- `redis`：缓存、队列与向量检索后端

## 启动

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1
```

脚本会自动从 `docker-desktop/.env.example` 生成 `docker-desktop/.env`，然后构建并启动服务。

## 访问

```text
http://localhost
```

默认账号：

```text
admin / 123456
```

MCP SSE 地址：

```text
http://localhost:8765/sse
```

## 配置 AI 模型

编辑：

```text
docker-desktop/.env
```

如果模型代理运行在宿主机，例如 CPAMC 的 `8317` 端口，Docker 容器内应使用：

```env
AI_SERVICE_MODEL_PROVIDER=openai-compatible
AI_SERVICE_MODEL_BASE_URL=http://host.docker.internal:8317/v1
AI_SERVICE_MODEL_NAME=gpt-5.4-mini
AI_SERVICE_MODEL_API_KEY=你的密钥
```

保存后重建/重启：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1 -ForceRecreate -Services api web
```

## 常用命令

构建镜像：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-build.ps1
```

启动服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1
```

停止服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-down.ps1
```

强制重建指定服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1 -NoCache -ForceRecreate -Services web nginx
```

## 目录结构

- `docker-compose.yml`：服务编排入口
- `.env.example`：环境变量模板
- `nginx/`：Nginx 配置
- `postgres/`：PostgreSQL 配置与数据目录占位
- `redis/`：Redis 配置与数据目录占位
- `database-init/`：数据库初始化 SQL
- `api/data/`：后端数据和测试产物落盘目录
- `logs/`：服务日志目录

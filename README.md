# AI Test Platform / AI+测试平台

## 项目介绍

AI+测试平台是一套面向测试团队的智能测试工作台，目标是把需求分析、测试用例设计、接口测试、UI 自动化、性能测试、安全扫描、报告汇总和 AI 助手放在一个统一平台里。

平台包含：

- Web 控制台：项目、需求、用例、接口测试、自动化测试、报告与设置页面
- AI 后端服务：对接 OpenAI 兼容模型，提供 AI 对话、需求分析、测试建议和工具调用能力
- MCP 工具服务：让 AI 助手可以调用平台能力，例如项目、需求、用例、执行、报告和安全扫描
- API runner：执行接口测试用例
- UI runner：基于 Playwright 执行 UI 自动化用例
- Docker 部署配置：适合服务器或开发环境统一部署
- Windows 便携包：适合没有 Docker 的 Windows 机器双击启动

接口设计文档、真实环境变量、本地数据库、缓存、构建产物和依赖目录不会提交到仓库。

## 使用方式一：Windows 一键启动版

适合希望“下载后双击运行”的场景，不需要 Docker Desktop。

1. 在 GitHub Releases 下载 `AI-Test-Platform-Portable.zip`。
2. 解压压缩包。
3. 双击 `AI-Test-Platform.exe`。
4. 浏览器会自动打开：

```text
http://127.0.0.1:3000
```

默认账号：

```text
admin / 123456
```

启动器采用轻量在线安装方式：压缩包不再内置 `node_modules`、Python 虚拟环境和 Playwright 浏览器内核，第一次运行会自动执行前端依赖安装、后端依赖安装、Web 构建和 Chromium 下载。首次运行需要网络，时间取决于 npm、PyPI 和 Playwright 下载速度；完成后依赖会保存在本地目录，后续启动会快很多。

本机需要已有：

```text
Node.js 20+
Python 3.11+
```

运行数据会保存在 `runtime/data`，日志会写入 `runtime/logs`。如果首次安装失败，先看 `runtime/logs/install.log`；网络恢复或装好缺少的运行环境后，再双击 `AI-Test-Platform.exe` 会继续安装。

### 配置 AI 模型

首次启动会生成：

```text
runtime/config.env
```

如果使用本机 CPAMC 代理，通常这样配置：

```env
AI_SERVICE_MODEL_PROVIDER=openai-compatible
AI_SERVICE_MODEL_BASE_URL=http://127.0.0.1:8317/v1
AI_SERVICE_MODEL_NAME=gpt-5.4-mini
AI_SERVICE_MODEL_API_KEY=你的密钥
```

保存后重新双击 `AI-Test-Platform.exe` 启动即可。

## 使用方式二：Docker Desktop 部署

适合需要 PostgreSQL、Redis、Nginx、MCP 服务一起编排的完整部署场景。

1. 安装 Docker Desktop，并确认支持 `docker compose`。
2. 在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1
```

3. 打开：

```text
http://localhost
```

Docker 部署会启动：

- `nginx`：统一入口与反向代理
- `web`：前端控制台
- `api`：后端业务与 AI 服务
- `mcp`：AI 助手 MCP 工具服务
- `postgres`：业务数据库
- `redis`：缓存、队列与向量检索后端

MCP SSE 地址：

```text
http://localhost:8765/sse
```

常用命令：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-build.ps1
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1
powershell -ExecutionPolicy Bypass -File scripts/docker-down.ps1
```

如需强制重建前端与网关：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1 -NoCache -ForceRecreate -Services web nginx
```

## 目录说明

- `apps/web`：Next.js 前端应用
- `services/ai-service`：FastAPI 后端服务
- `services/test-platform-mcp`：AI 助手 MCP 工具服务
- `workers/api-runner`：接口测试执行器
- `workers/ui-runner`：UI 自动化执行器
- `packages/shared-schema`：共享协议与类型
- `docker-desktop`：Docker Compose、Nginx、PostgreSQL、Redis 与环境模板
- `scripts`：Docker 构建、启动、停止脚本
- `packaging/launcher`：Windows 便携版启动器源码

## English

AI Test Platform is an intelligent testing workspace for QA teams. It combines requirements analysis, test case design, API testing, UI automation, performance testing, security scanning, reporting, and an AI assistant in one platform.

Use the Windows package from GitHub Releases if you want to start the platform by double-clicking `AI-Test-Platform.exe` without Docker. The package is intentionally lightweight: on the first run it installs npm packages, Python packages, builds the Next.js web app, and downloads the Playwright Chromium browser. Node.js 20+ and Python 3.11+ must already be available on the machine. Use the Docker scripts if you want the full Docker Compose deployment with PostgreSQL, Redis, Nginx, backend, web, runners, and MCP service.

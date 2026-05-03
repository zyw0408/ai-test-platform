# AI+测试平台 API 接口文档

## 1. 架构概览

后端采用 FastAPI，基于模块化路由设计，每个业务领域拥有独立路由与服务层，并由 `app/main.py` 统一注册。

### 核心模块

| 模块 | 路径前缀 | 主要功能 |
| :--- | :--- | :--- |
| Auth | `/auth` | 用户登录、注册、个人中心、密码管理 |
| Users | `/settings` | AI 模型配置、API Key 管理、用户列表 |
| Teams | `/teams` | 组织架构、团队成员、角色管理 |
| Projects | `/projects` | 项目创建、搜索、多项目隔离 |
| Requirements | `/requirements` | 需求分析、PRD 导入、自动化测试方案生成 |
| Testing | `/testing` | API 测试、性能测试、执行流水线 |
| Cases | `/cases` | 测试用例库、跨项目用例管理 |
| AI | `/ai` | AI 对话、用例生成、失败诊断 |
| Integrations | `/integrations` | Smithery 与 MCP 工具链接入 |
| Reports | `/reports` | 测试大盘、执行报告、AI 归因分析 |

## 2. 接口摘要

### 认证模块

- `POST /auth/login`
- `POST /auth/register/password`
- `POST /auth/register/sms/send-code`
- `GET /auth/me`
- `POST /auth/change-password`

### 项目与团队

- `GET /projects`
- `GET /projects/search?q=xxx`
- `GET /teams`

### 需求与测试设计

- `GET /requirements`
- `POST /requirements/analyze`
- `POST /ai/cases/generate`
- `GET /cases`
- `POST /cases`

### 测试执行

- `GET /testing/collections`
- `POST /testing/runs`
- `POST /testing/performance/run`
- `GET /testing/runs`

### AI 与集成

- `POST /ai/chat`
- `GET /ai/ops/{id}`
- `GET /integrations/smithery/status`
- `POST /integrations/smithery/connections`

### 报表

- `GET /reports/dashboard`
- `GET /reports/run/{run_id}`

## 3. 全局规范

### 认证

除注册与登录接口外，所有请求应携带：

`Authorization: Bearer <your_access_token>`

### 错误码

- `200/201`：成功
- `401`：未授权或 Token 过期
- `403`：权限不足
- `404`：资源不存在
- `500`：服务器内部错误

### 交互式文档

- Swagger UI：`http://localhost:8000/docs`
- ReDoc：`http://localhost:8000/redoc`

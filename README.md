# AI+测试平台

面向企业测试团队的 AI 测试工作台，覆盖“项目/需求/用例/接口测试/自动化测试/性能测试/安全测试/报告”全流程。

## 1. 项目结构

- `apps/web`：前端控制台（Next.js）
- `services/ai-service`：后端 AI 与业务 API（FastAPI）
- `services/test-platform-mcp`：平台 MCP 服务
- `workers/api-runner`：API 执行器
- `workers/ui-runner`：UI 执行器
- `packages/shared-schema`：共享类型与协议
- `infra`：中间件与部署相关配置
- `docs`：项目文档

## 2. 当前核心能力

- 项目、需求、测试用例的增删改查
- 接口测试集合管理、请求编排、执行与结果查看
- AI 辅助：
  - 需求分析与测试建议
  - 工具调用（含 MCP 工具）
  - 表单自动填充协议（`form_fill`）
- 性能测试与安全扫描入口
- 报告汇总与执行趋势查看

## 3. Docker 部署

### 3.1 准备

- 安装 Docker Desktop（需支持 `docker compose`）
- 按需修改 `docker-desktop/.env`；如果文件不存在，脚本会自动由示例文件生成

示例环境文件：

- `docker-desktop/.env.example`

### 3.2 构建镜像

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-build.ps1
```

### 3.3 启动服务

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1
```

前端改动后建议强制重建 `web` 与 `nginx`：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1 -NoCache -ForceRecreate -Services web nginx
```

默认会启动以下服务：

- `nginx`：统一入口与反向代理
- `web`：Next.js 前端
- `api`：FastAPI 后端
- `postgres`：PostgreSQL
- `redis`：Redis

默认访问地址：

- 前端入口：`http://localhost`
- 后端由 `nginx` 转发给前端应用，前端再访问内部 `api`

### 3.4 停止服务

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-down.ps1
```

## 4. 目录说明

- `apps/web`：前端应用及其 Dockerfile
- `services/ai-service`：主后端服务及其 Dockerfile
- `services/test-platform-mcp`：MCP 服务
- `workers/api-runner`：API 执行器
- `workers/ui-runner`：UI 自动化执行器
- `packages/shared-schema`：前后端共享类型
- `docker-desktop`：Compose、环境文件、nginx/postgres/redis 配置、日志与数据映射目录
- `docs/api`：接口文档
- `scripts`：仅保留 Docker 构建、启动、停止脚本

## 5. 默认访问与账号

- 前端默认地址：`http://localhost`
- 内部后端服务地址：`http://api:8000`
- 默认管理员（如未改环境变量）：
  - 用户名：`admin`
  - 密码：`123456`

## 6. 关键环境变量

请参考：

- `apps/web/.env.local.example`
- `services/ai-service/.env.example`
- `services/test-platform-mcp/.env.example`
- `docker-desktop/.env.example`

## 7. MCP 与 AI 配置建议

- 内置 MCP 建议保持只读基础能力（filesystem/fetch/playwright）
- 外部 MCP 通过设置页搜索并安装（npm 包）
- 自定义规则（custom rules）建议按“身份、语气、输出结构、禁用项、执行边界”分条维护

## 8. 说明

仓库当前只保留 Docker 交付路径，不再维护旧的 zip 打包脚本与本地中间件快捷脚本。

## 9. Docker 异常恢复

如果出现 `docker ... 500 Internal Server Error`，通常是 Docker Desktop Linux Engine 或镜像存储层异常。处理顺序：

1. Docker Desktop -> Troubleshoot -> `Clean / Purge data`
2. 若仍失败，执行 `Reset to factory defaults`
3. 然后重跑：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1 -NoCache -ForceRecreate -Services web nginx
```

# 后端接口核心契约设计 - 04 项目/需求文档/测试用例

本文件用于约束 `projects / specs / requirements / cases` 四个核心域的接口与字段命名，避免前后端字段偏差。

## 1. 字段命名基线

- 数据库列使用 `snake_case`（例如 `source_spec_id`）。
- API 出入参统一使用 `camelCase`（例如 `sourceSpecId`）。
- `cases` 只接受 `specId`（来自 `specs.id`），不接受 `requirement.id`。

### 1.1 关键字段映射

| 语义 | 数据库字段 | API 字段 |
|---|---|---|
| 需求关联文档 ID | `requirements.source_spec_id` | `sourceSpecId` |
| 需求所属项目 ID | `requirements.project_id` | `projectId` |
| 用例关联文档 ID | `entities.payload.specId` | `specId` |
| 用例所属项目 ID | `entities.payload.projectId` | `projectId` |

## 2. 核心接口契约

### 2.1 项目

- `GET /projects`
- `POST /projects`
  - Request: `{ name: string, description?: string }`
  - Response: `Project`

### 2.2 需求文档（Specs）

- `GET /specs?projectId=<id>`
  - 返回 `SourceSpec[]`
  - 说明：当传 `projectId` 时，会尝试将 `requirements.source_spec_id` 为空的需求补齐到 `specs`。
- `POST /specs/ingest`
  - FormData: `projectId, sourceType, title?, sourceUrl?, content?, file?`
  - Response: `SourceSpec`

### 2.3 需求分析（Requirements）

- `GET /requirements/search`
- `POST /requirements`
  - Request: `{ projectId, title, content, sourceSpecId?, tags? }`
  - 行为：当 `sourceSpecId` 为空时，后端会先创建一条 `specs`，再写入 `requirements.source_spec_id`。
  - Response: `Requirement`
- `POST /requirements/import`
  - FormData: `projectId, sourceSpecId?, file, dedupe, rollbackOnError, strictTemplate`
  - 行为：当 `sourceSpecId` 为空时，后端会自动创建导入来源 `spec`。

### 2.4 测试用例（Cases）

- `GET /cases/search`
- `POST /cases`
  - Request: `{ projectId, specId, kind, title, objective, steps, assertionHints, payload }`
  - 校验：
    - `projectId` 必须存在且未删除
    - `specId` 必须存在且未删除
    - `spec.projectId` 必须等于 `projectId`
- `POST /cases/generate`
  - Request: `{ projectId, specId, kinds }`
  - 与 `POST /cases` 相同的 `projectId/specId` 归属校验。

## 3. 联调必检清单（每次改接口都要同步）

1. 修改了后端请求/响应字段：同步本文件与前端类型定义。
2. 修改了数据库列：同步 `infra/postgres/init/01-init.sql` 与 API 映射表。
3. 修改了 `project/spec/requirement/case` 归属关系：同步校验规则描述。
4. 修改了删除/回收站行为：同步“是否过滤 `deleted_at`”的查询说明。

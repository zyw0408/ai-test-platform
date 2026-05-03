# 接口补充说明

## 认证与个人资料

### 获取当前用户

**接口**：`GET /api/auth/me`

### 更新个人资料

**接口**：`PUT /api/auth/profile`

请求示例：

```json
{
  "name": "New Name",
  "realName": "John Doe",
  "avatar": "https://..."
}
```

## AI 设置

### 获取个人 AI 配置

**接口**：`GET /api/settings`

### 保存个人 AI 配置

**接口**：`POST /api/settings`

## 团队管理

### 获取团队与成员

**接口**：`GET /api/teams`

## AI 助手

### 流式对话

**接口**：`POST /api/ai/chat`

**响应类型**：`text/event-stream`

## 安全扫描

### 发起异步扫描

**接口**：`POST /api/security/scan/start`

请求关键字段：

```json
{
  "projectId": "proj_xxx",
  "collectionIds": ["acol_xxx"],
  "targetUrl": "https://example.com",
  "maxDiscoveredUrls": 8,
  "scanTypes": ["owasp_api", "pii_scan", "auth_bypass"],
  "deepScan": true
}
```

### 同步扫描

**接口**：`POST /api/security/scan`

### 获取任务

**接口**：`GET /api/security/scan/tasks/{taskId}`

### 取消任务

**接口**：`POST /api/security/scan/tasks/{taskId}/cancel`

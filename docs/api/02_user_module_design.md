# 用户模块设计（低耦合 / 高内聚）

## 目标

- 支持多身份源：`password`、`sms(phone)`、`wechat(openid/unionid)`
- 支持用户资料：昵称、头像、展示名
- 支持隐私保护：手机号与微信标识不落明文
- 可持续扩展：后续新增第三方身份（钉钉、企微、GitHub）不改核心用户表

## 领域拆分

### 1) 核心用户表：`users`

职责：只存用户主体与授权控制相关字段（角色、状态、时间戳）

关键字段：

- `id`, `username`, `role`, `is_active`
- `name`（展示名）
- `nickname`, `avatar_url`（资料）
- `created_at`, `updated_at`, `last_login_at`

### 2) 密码凭据：`user_password_credentials`

职责：存放密码哈希，和 `users` 解耦。

- `user_id`（PK, FK -> users.id）
- `password_hash`
- `created_at`, `updated_at`

### 3) 手机号身份：`user_phone_identities`

职责：手机号登录身份，不在 `users` 放明文手机号。

- `user_id`（唯一）
- `phone_hash`（HMAC-SHA256，用于精确检索）
- `phone_cipher`（Fernet 对称加密密文）
- `phone_last4`（展示掩码）
- `verified_at`, `created_at`, `updated_at`

### 4) 微信身份：`user_wechat_accounts`

职责：微信登录与绑定，不污染用户核心表。

- `user_id`（唯一）
- `openid_hash`, `openid_cipher`
- `unionid_hash`, `unionid_cipher`
- `nickname`, `avatar_url`（来自微信档案，可覆盖展示）
- `profile_cipher`（加密的原始 profile）
- `last_bound_at`, `created_at`, `updated_at`

### 5) 登录审计：`user_login_events`

职责：登录行为审计（成功/失败、方式、客户端信息）。

- `user_id`（可空）
- `method`, `success`, `detail`
- `ip`, `user_agent`
- `created_at`

## 隐私与加密策略

实现位置：`services/ai-service/app/privacy.py`

- 查找字段：`hash`（不可逆）
  - 手机号：`hash_phone(phone)`
  - 微信：`hash_wechat_openid/unionid`
- 回溯字段：`cipher`（可逆）
  - Fernet 对称加密
- 展示字段：
  - 手机号只返回掩码（如 `***8000`）

配置项：

- `AI_SERVICE_PRIVACY_HASH_SECRET`
- `AI_SERVICE_PRIVACY_FERNET_KEY`（可空，空时基于 hash secret 派生）

## 低耦合策略

- 用户主表与身份表解耦：新增登录源只需新增 identity 表和 service 方法。
- 登录策略在 `UserAuthService` 内聚，不向 route 泄露存储细节。
- 主流程只依赖 `UserAuthService` 抽象，不依赖具体 SQL 字段。

## 扩展建议

- 新增 `user_external_accounts`（provider + provider_user_id_hash）统一外部身份模型。
- 引入 `user_profile_revisions` 记录昵称/头像历史。
- 登录审计可异步写入消息队列，降低主链路延迟。

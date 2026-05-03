# 微信 OAuth 与登录风控

## 微信 OAuth 登录

`POST /auth/login` 支持两种微信参数：

1. `wechatCode`（推荐，正式 OAuth 回调 code）
2. `wechatOpenId`（兼容模式，直接传 openId）

当传 `wechatCode` 时，服务端会：

1. 调用微信 `access_token` 接口换取 `openid/unionid`
2. 尝试拉取用户昵称与头像
3. 执行本地用户登录/绑定流程

### 配置

- `AI_SERVICE_WECHAT_OAUTH_ENABLED=true`
- `AI_SERVICE_WECHAT_APP_ID=...`
- `AI_SERVICE_WECHAT_APP_SECRET=...`
- `AI_SERVICE_WECHAT_HTTP_TIMEOUT_SECONDS=5`

## 登录风控（账号 + IP）

风控维度：

- 账号（hash 后）
- IP（hash 后）

机制：

1. 连续失败达到阈值 -> 锁定
2. 锁定期间登录返回 `429`
3. 登录成功会清除该账号/IP失败计数

### 配置

- `AI_SERVICE_LOGIN_FAIL_LIMIT=5`
- `AI_SERVICE_LOGIN_FAIL_WINDOW_SECONDS=600`
- `AI_SERVICE_LOGIN_LOCK_SECONDS=900`

## 管理员解锁接口

`POST /auth/risk/unlock`

请求体示例：

```json
{
  "method": "password",
  "account": "target_user"
}
```

或按 IP 解锁：

```json
{
  "method": "password",
  "ip": "127.0.0.1"
}
```

鉴权：管理员 token。

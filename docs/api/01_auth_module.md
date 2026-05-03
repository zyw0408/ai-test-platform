# 后端接口核心契约设计 - 01 Auth 登录模块

本文件定义了前端 Next.js GUI 与后端核心引擎间的标准握手协议。前后端目前处于边写边联调的阶段，前端通过直接调用 `/api/auth/login` 等中间路由穿透到后端。

---

## 1. 账号/短信 聚合登录接口
**Endpoint:** `POST /api/auth/login`
**Content-Type:** `application/json`

### 1.1 请求参数 (Request Body)
| 字段名   | 数据类型 | 必填 | 默认/说明 |
|---------|---------|------|-----------|
| method  | string  | 是   | 登录介质枚举：`password` (密码体系) 或 `sms` (手机验证码体系) |
| username| string  | 否   | 当 `method=password` 时有效，传入邮箱/用户名/账单号 |
| password| string  | 否   | 当 `method=password` 时有效，前端已使用 SHA256 脱敏 |
| phone   | string  | 否   | 当 `method=sms` 时有效，用户大陆手机号 |
| code    | string  | 否   | 当 `method=sms` 时有效，由短信网关签发的 6 位动态密码 |

---

### 1.2 响应协议 (Response Body) - 成功场景
**Status Code:** `200 OK`
```json
{
  "code": 0,
  "message": "登录环境检测安全，授权成功",
  "data": {
    "token": "eyJhbG..",             // JWT 标准承载 Token，需下放进 LocalStorage/Cookie
    "expires_in": 7200,              // Token 有效期 (秒)
    "user": {
      "id": "USR-109012X",
      "name": "Admin 张",
      "avatar": "https://cdn.example.com/tx.png",
      "role": "admin"                // 角色权限路由护城河：admin/tester/guest
    }
  }
}
```

---

### 1.3 响应协议 (Response Body) - 校验拦截场景
当请求的账密不对，或触发高频风控限制时：
**Status Code:** `401 Unauthorized` 或 `400 Bad Request`
```json
{
  "code": 40101, // 具体业务子错误码 (前台通过该枚举翻译为不同的提示框)
  "message": "账号或密码错误 (剩余 3 次重试机会)",
  "details": {
    "lock_time": null
  }
}
```

---

## 2. 刷新凭证接口 (无感续期)
*在长时间编写用例时保证 Session 永不断线*
**Endpoint:** `POST /api/auth/refresh`

### 2.1 请求参数
*(基于已有 Header 里的 Authorization 字段和 Cookie HttpOnly RefreshToken，无额外 Body)*

### 2.2 响应体
```json
{
  "code": 0,
  "data": {
    "token": "新的短期操作 Token",
    "expires_in": 7200
  }
}
```

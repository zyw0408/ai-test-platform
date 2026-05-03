# Docker Desktop 部署目录

这是项目的统一交付目录，面向 Docker Desktop / Docker Compose 部署。

## 目录结构

- `docker-compose.yml`：整套服务编排入口
- `.env.example`：部署环境变量模板
- `nginx/`：Nginx 反向代理配置
- `postgres/`：PostgreSQL 配置与数据目录
- `redis/`：Redis 配置与数据目录
- `database-init/`：数据库初始化 SQL
- `api/data/`：后端业务数据、产物落盘目录
- `logs/`：各服务日志目录

## 常用脚本

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/docker-build.ps1
powershell -ExecutionPolicy Bypass -File scripts/docker-run.ps1
powershell -ExecutionPolicy Bypass -File scripts/docker-down.ps1
```

## 访问地址

- 平台入口：`http://localhost`

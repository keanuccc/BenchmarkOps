# Docker 部署指南

## 前置条件

- [Docker](https://docs.docker.com/get-docker/) 20.10+
- [Docker Compose](https://docs.docker.com/compose/) 2.0+（Docker Desktop 自带）

验证安装：

```bash
docker --version
docker compose version
```

## 快速开始

在项目根目录执行：

```bash
docker compose up --build -d
```

这会自动构建镜像并以后台模式启动：

| 服务     | 端口  | 说明                           |
|----------|-------|--------------------------------|
| frontend | 3000  | Next.js 前端应用               |
| backend  | 8000  | FastAPI 后端 API（ARQ 入队）   |
| worker   | -     | ARQ 评测 worker（消费 Redis 队列） |
| redis    | 6379  | 任务队列存储（AOF 持久化）     |

访问：
- 前端页面：http://localhost:3000
- 后端 API 文档：http://localhost:8000/docs

停止服务：

```bash
docker compose down
```

## 自定义配置

### 环境变量

后端读取 `backend/.env` 文件中的配置。如果该文件不存在，使用默认值运行（Mock 模式 + SQLite）。

复制示例文件作为起点：

```bash
cp backend/.env.example backend/.env
```

然后编辑 `backend/.env` 中的关键项：

- `API_TOKEN` — 设置此值启用 API 认证（请求头 `Authorization: Bearer <token>`）
- `DATABASE_URL` — 默认 SQLite；如需 PostgreSQL 请修改
- `OPENROUTER_API_KEY` / `QINIU_API_KEY` — 接入真实 LLM 提供商
- `BACKEND_CORS_ORIGINS` — 允许的前端域名
- `TASK_QUEUE_BACKEND` — `asyncio`（进程内，默认）或 `arq`（Redis 分布式队列）；compose 中 backend/worker 已固定为 `arq`
- `REDIS_DSN` — ARQ 使用的 Redis 连接串（compose 内为 `redis://redis:6379/0`）

前端通过 docker-compose.yml 中 `environment` 段配置 `NEXT_PUBLIC_API_BASE_URL`，指向后端地址。

### 生产环境

将 `APP_ENV=production` 写入 `.env`，并设置 `API_TOKEN` 启用认证。

### 任务队列（Redis + ARQ）

- compose 会启动 `redis`（开启 AOF 持久化）与 `worker`（`uv run arq app.worker.WorkerSettings`）两个服务，backend 通过 `TASK_QUEUE_BACKEND=arq` 把评测任务写入 Redis 队列。
- 支持多 worker / 多副本水平扩展：额外 `docker compose up --scale worker=N` 即可。
- **Redis 持久化**：compose 已用 `--appendonly yes` 开启 AOF，数据落在命名卷 `redis_data`；请勿在生产关闭 AOF，否则 Redis 重启会丢失队列中的任务。
- **SQLite 多写者约束**：compose 默认 backend + worker 共享 SQLite 文件，多写者场景可能出现 `database is locked`。生产环境请切换 PostgreSQL（见 [postgres-migration-guide.md](postgres-migration-guide.md)），或保持单 backend + 任务侧 worker 的形态。

## 数据持久化

SQLite 数据库文件 (`benchmarkops.db`) 挂载到 Docker 命名卷 `db_data`。即使容器重建或删除后重启，数据仍然保留。

如果需要手动备份：

```bash
docker run --rm -v benchmarkv1_db_data:/data -v /tmp:/backup alpine tar czf /backup/benchmarkops-backup.tar.gz -C /data .
```

恢复：

```bash
docker run --rm -v benchmarkv1_db_data:/data -v /tmp:/backup alpine tar xzf /backup/benchmarkops-backup.tar.gz -C /data
```

## 切换到 PostgreSQL

1. 在 `docker-compose.yml` 中添加 PostgreSQL 服务：

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: benchmarkops
      POSTGRES_PASSWORD: benchmarkops
      POSTGRES_DB: benchmarkops
    volumes:
      - pg_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

volumes:
  db_data:
  pg_data:
```

2. 修改 `backend/.env`：

```
DATABASE_URL=postgresql+asyncpg://benchmarkops:benchmarkops@postgres:5432/benchmarkops
```

3. 重新构建并启动：

```bash
docker compose up --build -d
```

## 常用命令

```bash
# 查看运行状态
docker compose ps

# 查看日志
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f worker

# 进入后端容器 shell
docker compose exec backend sh

# 进入前端容器 shell
docker compose exec frontend sh

# 完全清理（含数据卷）
docker compose down -v

# 仅停止容器（保留数据和卷）
docker compose stop
```

## 故障排查

### 构建失败

确保项目根目录包含 `backend/pyproject.toml` 和 `backend/uv.lock`。如果没有 uv.lock，先在后端目录运行 `uv lock` 生成。

### 端口冲突

如果 3000 或 8000 端口被占用，修改 `docker-compose.yml` 中 `ports` 映射的前面部分（宿主机端口），例如 `"8080:8000"`。

### CORS 错误

如果前端无法连接后端，检查 `backend/.env` 中的 `BACKEND_CORS_ORIGINS` 是否包含前端的 URL（如 `http://localhost:3000`）。

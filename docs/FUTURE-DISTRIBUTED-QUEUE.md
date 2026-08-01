# 远期大项：分布式评测任务队列（交接文档）

> 本文档是给下一个对话窗口的交接说明。背景：BenchmarkOps 当前评测任务由进程内
> `AsyncioTaskQueue` 执行（`backend/app/evaluation/task_queue.py`），单进程内可用，
> 但重启丢任务、无法水平扩展。此前已完成一轮"任务持久化 v1"（`evaluation_tasks`
> 表 + 重启恢复标记），本大项在此基础上把它升级为真正的分布式队列。

> **实施状态（2026-08-01 更新）：本大项已在分支 `codex/distributed-queue` 落地。**
> - 已实现：`ArqTaskQueue`（Redis 持久化入队/取消/运行中查询）、`app/worker.py`
>   （ARQ WorkerSettings + `run_experiment_task`）、配置开关
>   `TASK_QUEUE_BACKEND=asyncio|arq`、计费安全的重试策略（仅 `RetryableTaskError`
>   重试）、worker 崩溃接管（stale running → queued 重置）、取消语义（非阻塞
>   abort 标记 + DB 状态为准）、重试/取消后残留 ARQ 状态清理（同实验 ID 可重新
>   入队）、ARQ 模式下启动恢复跳过。
> - 测试：`tests/test_distributed_queue.py` 15 个用例（Redis 不可用时自动跳过）；
>   全量回归 `308 passed`（原基线 293 + 新增 15），默认 asyncio 后端不受影响。
> - 部署：docker-compose 新增 `redis`（AOF）与 `worker` 服务；`README.md`、
>   `docs/docker-deployment.md`、`backend/.env.example` 已同步。

## 1. 现状（已完成的部分）

- `evaluation_tasks` 表（迁移 v15）：每次运行一条审计记录，生命周期
  `queued → running → succeeded/failed/cancelled`，含 `started_at` /
  `finished_at` / `error`。模型 `app/models/task.py`，仓库 `app/repositories/task.py`，
  生命周期写入集中在 `app/evaluation/task_records.py`。
- 提交运行在 `ExperimentService.run`（`app/services/experiment_service.py`）创建 queued 记录；
  runner 开始/结束/取消标记；启动恢复（`app/main.py:_recover_stale_experiments`）把
  stale 实验与任务标记为 failed。
- `TaskQueue` 抽象（`app/evaluation/task_queue.py`）已有 `submit` /
  `get_running_tasks` / `cancel_task` 接口，设计上"换实现只改接线"。

## 2. 目标

把任务从"进程内内存队列"升级为"Redis 持久化队列"，支持：

1. **多 worker / 多副本**：多个 backend 进程共同消费队列，任务只执行一次（幂等守卫已有：
   `ExperimentRepository.set_running_if_not_running` 的 CAS）。
2. **重启不丢任务**：队列在 Redis，进程崩溃后任务仍可被其他 worker 领取。
3. **失败重试策略**（可选，默认不自动重跑计费型评测）：仅对明确的瞬态错误
   （`database is locked`、网络超时、429 退避后）做有限次重试；配额耗尽类错误不重试。
4. **排队可见性**：`/experiments/running` 已返回 queued + running，升级后保持一致。

## 3. 推荐方案：ARQ（轻量，兼容 asyncio 架构）

项目是纯 asyncio 栈（FastAPI + aiosqlite/asyncpg），选 **ARQ** 比 Celery 契合度更高：

- `arq` + `redis` 依赖（后端 `pyproject.toml` 添加）。
- 定义 worker 入口（新文件 `backend/app/worker.py`）：注册
  `run_experiment(experiment_id)` 为 ARQ 任务函数，运行时从 Redis 拉取。
- 用 ARQ 的 `create_pool` 替代 `AsyncioTaskQueue.submit`：入队即持久化。
- ARQ 自带重试（`max_tries` / `retry_after`），只在任务函数抛特定瞬态异常时启用。

### 接线点

- `app/evaluation/task_queue.py`：保留 `TaskQueue` 抽象；新增 `ArqTaskQueue`
  实现（`submit` 写入 Redis、`cancel_task` 用 job id 调用 `job.abort()`、
  `get_running_tasks` 从 Redis 查询活跃 job）。`task_queue` 单例按配置切换：
  `settings.task_queue_backend = "arq" | "asyncio"`。
- `ExperimentService.run`：提交前已创建 queued 任务记录，直接复用。
- `app/main.py` 启动恢复：保留现有逻辑（Redis 队列里仍可能有任务，worker 领取后
  会被 CAS 挡掉或正常执行——需实测并补充"领取到已 cancelled 实验"的分支测试）。
- `docker-compose.yml`：新增 redis 服务；`Dockerfile.backend` 启动命令改为
  `arq app.worker.WorkerSettings`（生产）或保持 uvicorn + 独立 worker 容器。

## 4. 实施步骤（建议顺序）

1. 后端加 `arq` + `redis` 依赖；写 `app/worker.py` 的 ARQ WorkerSettings，
   单测验证 `run_experiment` 可通过 ARQ 调用（Mock provider 下完整跑通一次）。
2. 实现 `ArqTaskQueue`（submit/cancel/running 查询），配置开关切换；保留
   `AsyncioTaskQueue` 作为默认（`task_queue_backend=asyncio`），CI 不受影响。
3. 幂等与并发测试：两个 worker 同时消费同一任务，断言只执行一次
   （复用 `tests/test_run_race.py` 思路）。
4. 重启恢复测试：入队后杀 worker → 另一 worker 领取执行；`evaluation_tasks`
   状态机全程一致（新增 `tests/test_distributed_queue.py`）。
5. 重试策略：仅瞬态异常重试（新增异常标记，如 `RetryableTaskError`），
   配额耗尽（`ProviderQuotaExhaustedError`）不重试。
6. docker-compose 集成 + 文档更新。

## 5. 验收标准

- 默认配置（`asyncio`）下全部现有测试保持通过（当前基线 293 passed）。
- `task_queue_backend=arq` 下：任务入队后重启 backend 进程，任务仍被 worker 执行；
  `evaluation_tasks` 状态最终为 succeeded/failed/cancelled 之一。
- 双 worker 并发消费同一任务只执行一次（CAS 生效）。
- 排队可见性不变：`/experiments/running` 返回 queued + running。

## 6. 注意事项 / 坑

- **SQLite 单写者约束**：多 worker 共享 SQLite 会再次触发 `database is locked`。
  本大项应同时把生产默认切到 PostgreSQL（`DATABASE_URL=postgresql+asyncpg://...`），
  或保持"生产单 backend + 多 worker 仅任务侧"的约束并在 README 写明。
- **计费安全**：默认不自动重跑；重试仅限调用前失败（未产生上游 token 消耗）的
  瞬态错误。429/配额耗尽一律标 failed，人工重试。
- **Redis 持久化**：ARQ 任务在 Redis 中，Redis 本身要开 AOF 持久化，否则 Redis 重启
  同样丢任务——把"Redis 持久化"写进部署文档。
- **取消语义**：`job.abort()` 会中断 runner 的协程；runner 需在 `CancelledError`
  路径里保持现有"标记 cancelled + task 记录 cancelled"行为（已具备）。

## 7. 相关文件索引

- 队列抽象与单例：`backend/app/evaluation/task_queue.py`
- 任务记录生命周期：`backend/app/evaluation/task_records.py`
- 任务表模型/仓库：`backend/app/models/task.py`、`backend/app/repositories/task.py`
- 提交入口：`backend/app/services/experiment_service.py`
- 运行守卫（CAS）：`backend/app/repositories/experiment.py`
- 启动恢复：`backend/app/main.py`
- 配置：`backend/app/core/config.py`
- 部署：`docker-compose.yml`、`Dockerfile.backend`

## 8. 落地后的新增/变更文件

- 新增：`backend/app/worker.py`、`backend/app/evaluation/errors.py`、
  `backend/tests/test_distributed_queue.py`
- 修改：`backend/app/evaluation/task_queue.py`（`ArqTaskQueue` + 后端切换）、
  `backend/app/evaluation/runner.py`（取消守卫 + 瞬态锁错误标记）、
  `backend/app/services/experiment_service.py`（入队失败回滚为 failed）、
  `backend/app/main.py`（ARQ 模式跳过启动恢复）、`backend/app/core/config.py`、
  `backend/pyproject.toml`（`arq` + `redis` 依赖）、`docker-compose.yml`、
  `README.md`、`docs/docker-deployment.md`、`backend/.env.example`、
  `backend/tests/conftest.py`（测试用独立 Redis DB 15）
- 本地验证 Redis：本机 Redis 开启 `requirepass` 时，测试通过
  `REDIS_DSN=redis://:密码@localhost:6379/15` 环境变量注入（不写入仓库）。

# 从进程内队列到 Redis + ARQ：BenchmarkOps 分布式评测队列的工程演进

> 本文记录 BenchmarkOps 评测任务队列的一次真实演进：从"单进程内存队列"到
> "Redis 持久化 + 多 worker 消费"的过程，以及这背后三个容易被忽略的工程问题——
> **幂等、计费安全的重试、配额耗尽的识别**。

## 1. 背景：评测任务为什么需要队列

BenchmarkOps 的评测流程是一条异步流水线：用户创建实验 → 系统读取数据集 → 逐行
调用模型网关（OpenRouter / 七牛云 AI / Mock）→ 打分 → 汇总报告。一个 1000 行的
数据集评测可能持续几十分钟，显然不能放在 HTTP 请求里同步完成。

第一版实现是一个进程内的 asyncio 队列（`AsyncioTaskQueue`）：提交任务后由
事件循环消费。它足够让 Demo 跑通，但有两个硬伤：

1. **进程重启丢任务**。队列在内存里，`uvicorn --reload` 或部署发布都会中断
   进行中的评测，遗留实验只能被启动恢复逻辑标记为 failed。
2. **无法水平扩展**。一个进程能消费的并发有限，评测量大时只能排队等待。

## 2. 选型：为什么是 ARQ 而不是 Celery

项目是纯 asyncio 栈（FastAPI + SQLAlchemy 2.0 async + aiosqlite/asyncpg），
而 Celery 是同步 worker 模型，引入它意味着两套并发模型的长期共存。ARQ 是
纯 asyncio 的 Redis 任务队列，与现有代码契合度更高：

- 任务函数就是 async 函数，可以直接复用评测 runner；
- 队列持久化在 Redis（开启 AOF），进程崩溃后任务不丢；
- 自带 `max_tries` / `retry_after` 重试参数，但我们刻意**没有**用它的通用重试，
  而是只对特定异常重试（见第 4 节）。

实现上保留了 `TaskQueue` 抽象（`submit` / `get_running_tasks` /
`cancel_task`），通过配置项 `TASK_QUEUE_BACKEND=asyncio|arq` 切换，换实现不
改业务代码。

## 3. 多 worker 下的幂等：CAS 是底线

分布式队列最容易踩的坑是**同一任务被执行两次**。评测任务不是幂等的——每次调用
模型都要计费，重复执行等于双倍账单。

我们的防线分两层：

- 第一层：任务入队前先写 `evaluation_tasks` 审计记录（queued），worker 领取后通过
  `ExperimentRepository.set_running_if_not_running`（数据库层的 CAS）把实验状态
  从 queued 原子地置为 running。**谁 CAS 成功谁执行**，第二个 worker 抢到任务时
  发现状态已经不是 queued，直接放弃。
- 第二层：worker 崩溃接管。如果 worker 在执行中挂掉，实验会停留在 running；
  启动恢复逻辑把"超过心跳阈值仍未结束的 running 任务"重置为 queued，让其他
  worker 可以重新领取。

这两层配合，才能保证"任务只执行一次"不依赖 worker 的自觉，而是由数据库状态机
说了算。

## 4. 计费安全的重试：什么错误值得重试

队列系统最常见的错误是"无条件重试一切异常"。对评测平台这是危险的：如果模型
网关已经扣费、只是响应解析失败，重试同一行等于为同一个问题付两次钱。

我们的策略是给异常分三类：

| 异常类型 | 例子 | 是否重试 |
|---|---|---|
| 瞬态错误 | `database is locked`、网络超时、429 退避后仍可恢复 | 重试（有限次） |
| 计费前失败 | 请求还没发出去就失败 | 重试 |
| 计费后失败 / 配额耗尽 | Provider 已返回结果但解析失败；`429001`、`FreeQuotaExhausted` | **不重试**，标记 failed 人工处理 |

具体到代码，Qiniu provider 把 429 细分为两类：普通限流（瞬态，退避后重试）和
配额耗尽（如错误码 `429001` / `FailedOperation.FreeQuotaExhausted`），后者抛出
`ProviderQuotaExhaustedError`，runner 收到后**停止整个 run** 而不是逐行空转——
今天的免费额度用完了，等再久也不会恢复，继续重试只是浪费。

另外还有跨行熔断：连续 10 次 429（没有任何成功响应）就中止整个实验，而不是让
每行都背着指数退避空转到超时。

## 5. 落地形态与验证

- `docker-compose.yml` 新增 `redis`（AOF 持久化）与 `worker` 服务；
- 新增 `backend/app/worker.py`（ARQ WorkerSettings + `run_experiment_task`）；
- 新增 `tests/test_distributed_queue.py` 15 个用例（Redis 不可用时自动跳过），
  覆盖入队/取消/崩溃接管/幂等/重试策略；
- 默认仍是 asyncio 后端，CI 与本地开发不受影响；生产用 `TASK_QUEUE_BACKEND=arq`
  切换。

## 6. 教训

1. **队列的实现可以换，接口必须先抽象好**。`TaskQueue` 抽象让这次演进几乎是
   "接线"级别的工作量，业务层零改动。
2. **计费系统的重试策略不是工程细节，是财务正确性**。重试前先问一句：这个错误
   发生在计费之前还是之后？
3. **幂等要靠数据库状态机，不靠 worker 自觉**。任何分布式任务系统，CAS 都是
   最后一道闸。

---

相关代码：`backend/app/evaluation/task_queue.py`、`backend/app/worker.py`、
`backend/app/evaluation/runner.py`、`backend/app/providers/qiniu.py`；
部署文档：`docs/docker-deployment.md`、`docs/postgres-migration-guide.md`。

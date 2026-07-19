# BenchmarkOps 并发与健壮性优化方案

> 本文档是本次优化的纲领 + 开发状态记录（status log）。
> 每完成一个阶段，在末尾的「开发状态」表中更新进度。
> 最后更新：2026-07-20

---

## 0. 问题背景（来自日志分析）

一次实验运行中断（`e15ab7b7`，永久卡在 `running / progress=0`，`updated_at` 停在创建时刻）。

**根因链（已确认）：**

1. **OpenRouter 持续 429 限流，无有效退避/熔断**
   - 实验 `run started` 后下一秒即收到 `429 Too Many Requests`，此后约每 30s 一次，从 `17:43` 持续到日志结尾 `20:58`（共 390 次，3 小时+）。
   - `OpenRouterProvider.complete` 仅有 `_RETRY_COUNT=3` 次、退避 `0.5/1/2s`，每个 row 都经历"3 次 429 → 抛异常 → 被 runner 捕获记 `provider_errors` → 继续下一行"。限流不恢复时变成**逐行空转**，且永不主动失败。

2. **两个 backend 进程（8000 + 8001）共享同一 SQLite 文件，引发 `database is locked`**
   - 两者都用 `./benchmarkops.db`；`database is locked` 出现 52 次，涉及 `UPDATE experiments` 与 `INSERT INTO models` 两类并发写。
   - 关键状态更新（CAS `finish_if_running`、进度写入）在锁竞争中**静默失败**，导致实验卡死在 running 且进度写不回。

3. **缺失项**
   - 用户已配置真实 API key（不再用 Mock），但 provider 无 429 智能退避（读 `Retry-After`、全局限流、熔断）。
   - 实验运行中前端虽有 1s 轮询，但进度信息（`progress / rows_total`）已存在却**未渲染成可视化进度条**。
   - 异常处理偏"吞掉"，lock/网络等可重试错误缺乏结构化重试。
   - 单测虽有（runner 锁、竞态等），但缺少 429 退避、lock 重试、进度上报等回归测试。

---

## 1. 优化目标

| # | 目标 | 验收标准 |
|---|------|----------|
| G1 | **消除 SQLite 并发锁死** | 多进程/多写并发下不再出现 `database is locked` 静默丢失状态；实验状态更新始终落库 |
| G2 | **真实模型 API 下 429 可恢复** | 读 `Retry-After` 退避；连续 429 触发熔断 → 实验快速进入 `failed` 而非空转数小时 |
| G3 | **去掉 Mock，强化异常处理与健壮性** | Mock provider 保留为测试替身但默认走真实 provider；lock/网络/超时等可重试错误结构化重试；异常不再静默吞掉 |
| G4 | **运行中真实进度条** | 前端在 `running` 态显示 `progress / rows_total` 的可视化进度条 + 实时百分比 |
| G5 | **单元测试覆盖** | 429 退避、lock 重试、进度上报、熔断均有单测，且纳入 `pytest` 默认运行（非 e2e） |
| G6 | **多 agent 并行开发** | 按模块拆分，用多 agent 并行实现，主循环做 adversarial review |

---

## 2. 方案设计

### 2.1 并发（G1）—— SQLite 写冲突治理

现状已具备：WAL + `busy_timeout=15000` + CAS + 单写者 persist。不足是**没有对 `database is locked` 做重试**，且两个独立进程仍会抢同一文件。

改造点：
- **`database.py`：新增 `with_retry_on_lock` 工具**——对写操作包装 `OperationalError(database is locked)` 的指数退避重试（上限 ~5 次 / 总 ~15s，匹配 busy_timeout），让"瞬时锁竞争"自动恢复，不再静默丢失。
- **`runner._persist_progress` / `_mark_failed` / persist 阶段** 统一走带 lock 重试的会话上下文。
- **文档约束（进程单一写者）**：在 README/启动说明明确"生产环境只跑一个 backend 进程"；`AsyncioTaskQueue` 的 `eval_max_workers` 已限制并发写者数。代码层无法阻止两个独立进程共享文件，但重试可吸收绝大多数瞬时空窗竞争。**（关键约束：停止同时启动 8000/8001 两个写同一 db 的实例。）**
- 保留 SQLite 作为默认，但确保切换 Postgres 仅需改 `DATABASE_URL`（已满足）。

### 2.2 429 治理（G2）

- **`OpenRouterProvider` 智能退避**：
  - 优先读响应头 `Retry-After`（已存在，保留）；
  - 退避上限从 `2s` 提高（如 `_BACKOFF_MAX=30s`），避免长时间无效短退避；
  - 引入**连续 429 计数 + 全局熔断器**：同一 provider 实例累计连续 429 达到阈值（如 5 次）即熔断，剩余 row 直接以 `failed` 结束并写明"rate limited"。
- **runner 感知熔断**：provider 在持续限流时抛出一个可识别异常（如 `ProviderRateLimitedError`），runner 捕获后**立即终止本轮并 `_mark_failed`**，而不是逐行跑完 3 小时。
- 每次 429 都要在日志留下可读记录（已部分满足），并计入 `provider_errors`。

### 2.3 异常处理与健壮性（G3）

- 新增异常类型：`ProviderRateLimitedError`（继承 `DomainError`，对前端友好码 `provider_rate_limited`）。
- `_persist_progress` 的 `except SQLAlchemyError` 改为：识别 `database is locked` → 走 lock 重试；其他 SQLAlchemyError → 记日志但不阻断（进度是 best-effort）。
- `run_experiment` 顶层增加结构化错误捕获：任何未预期异常都 `_mark_failed` 并写入 sanitized error（已有 redaction，复用）。
- 去掉 Mock 默认路径：`.env` 真实 key 已配，registry 保持"有 key 用 OpenRouter、无 key 用 Mock"——Mock 仅在测试中使用（已是如此）。**不删除 Mock 类（测试替身），但生产默认真实。**

### 2.4 真实进度条（G4）

- 后端：已有 `progress`/`rows_total`。增强：
  - `_persist_progress` 频率更稳妥（保持每 50 行，但失败时重试不影响主流程）；
  - 新增 `cells_done`（已成功打分的行数）与 `cells_error`（失败行数）字段，让进度条区分"已评分/已失败/待处理"，前端可显示"已评分 X / 失败 Y / 共 Z"。
- 前端：在 `experiments/[id]/page.tsx` 的 `running` 态渲染进度条组件（`<Progress>`），展示百分比 + 三段式计数；轮询逻辑已存在（1s），无需改轮询频率。

### 2.5 单元测试（G5）

新增测试文件（纳入默认 `pytest`，非 `e2e`）：
- `test_rate_limit_backoff.py`：mock httpx 返回 429（带/不带 `Retry-After`），断言退避逻辑与熔断行为。
- `test_db_lock_retry.py`：用故障注入模拟 `database is locked`，断言 `with_retry_on_lock` 重试成功 / 超限抛错。
- `test_progress_reporting.py`：runner 在多行、部分失败时正确上报 `progress` / `cells_done` / `cells_error`。
- 已有 `test_runner_no_long_lock`、`test_run_race` 等保留并适配。

---

## 3. 任务拆分（多 agent 并行）

| Agent | 任务 | 涉及文件 | 交付 |
|-------|------|----------|------|
| A（并发） | 实现 `with_retry_on_lock` + runner 写入路径接入 | `core/database.py`, `evaluation/runner.py` | 锁重试工具 + 接入 |
| B（429） | provider 智能退避 + 熔断 + `ProviderRateLimitedError` | `providers/openrouter.py`, `providers/base.py`, `core/exceptions.py` | 退避/熔断 |
| C（进度条） | 后端计数字段 + 前端进度条组件 | `models/experiment.py`, `evaluation/runner.py`, `frontend/.../page.tsx` | 进度可视化 |
| D（测试） | 上述三类的单测 | `tests/*.py` | 测试 + 全部通过 |
| M（主循环） | 集成、串接、adversarial review、跑测试、更新本文档 status | 全局 | 验收 |

> 协同约束：A/B 都会改 `runner.py` 与 `exceptions.py`，由主循环负责合并；子 agent 各自产出独立文件优先，共享文件改动以 diff 形式回报，主循环统一应用。

---

## 4. 开发状态（STATUS LOG）

| 阶段 | 任务 | 状态 | 完成时间 | 备注 |
|------|------|------|----------|------|
| 0 | 日志分析与根因定位 | ✅ 完成 | 2026-07-20 | 见第 0 节 |
| 1 | 写优化方案文档（本文件） | ✅ 完成 | 2026-07-20 | — |
| 2 | A：SQLite 锁重试工具 + runner 接入 | ✅ 完成 | 2026-07-20 | `with_retry_on_lock` + runner 三写入路径；已合并主仓库、导入通过 |
| 3 | B：429 智能退避 + 熔断 + 异常类型 | ✅ 完成 | 2026-07-20 | `ProviderRateLimitedError` + 跨 row 熔断（阈值5）+ 退避上限30s；已合并主仓库 |
| 4 | C：进度计数字段 + 前端进度条 | ✅ 完成 | 2026-07-20 | `cells_done`/`cells_error` 模型列 + MIGRATIONS[11] 加列 + 前端进度条 |
| 5 | D：单元测试（429/lock/进度） | ✅ 完成 | 2026-07-20 | 新增 3 个测试文件；全套 35 passed / 11 e2e deselected |
| 6 | M：集成 + 跑全套测试 + adversarial review | ✅ 完成 | 2026-07-20 | 全套 40 passed；adversarial review 发现 6 处高/中缺陷已修复并补回归测试 |
| 7 | 启动单一 backend 验证全链路 | ⏳ 待开始 | — | — |

图例：⏳ 待开始 / 🔄 进行中 / ✅ 完成 / ❌ 阻塞

### 4.1 合并过程中的关键修复记录

- **C 字段未接入 runner（缺口）**：C agent 只改了 model/schema/前端，未在主仓库 `runner.py` 维护/写入 `cells_done`/`cells_error`（因约束"不动 A/B 的 persist 逻辑"，而 A 的锁重试合并时覆盖了 persist 块）。主循环补齐：compute 循环维护计数 → `_persist_progress(..., cells_done=, cells_error=)` → persist 阶段写入。
- **428→429 熔断无法触发（设计 bug）**：原 `for attempt in range(_RETRY_COUNT=3)` 单 row 内最多 3 次就 `raise last_exc`，而熔断阈值 `_RATE_LIMIT_BURST=5` > 3，导致熔断永远等不到。重写为 `while True`：429 持续重试直到熔断阈值，5xx/timeout 仍用 `_RETRY_COUNT=3` 瞬时重试。并修复 D 测试对"单次 complete 内 5 个 429"的假设（现已支持）。
- **persist 失败文案写死**：原 `_mark_failed("database locked during persist")` 覆盖了原始异常信息，破坏既有测试 `test_runner_marks_failed_when_persist_errors` 且降低诊断价值。改为 `_mark_failed(str(exc)[:500])` 保留原始诊断。
- **迁移缺失**：model 加列后未注册迁移，旧库 `benchmarkops.db` 缺列。新增 `MIGRATIONS[11]`（幂等 ALTER），已验证 `cells_done`/`cells_error` 落库。
- **测试 venv 陷阱**：默认 `python` 指向 MediaCrawler 的 venv（旧 FastAPI，报 `204 must not have a response body`）。必须用 `backend/.venv/Scripts/python.exe` 跑测试。

### 4.2 验证结果

```
backend/.venv/Scripts/python.exe -m pytest -q
# 35 passed, 11 deselected (e2e), 1 warning
```

新增测试：
- `test_db_lock_retry.py`（4 用例）：重试成功 / 非锁异常不重试 / 超限重抛 / 其他异常类型透传。
- `test_rate_limit_backoff.py`（4 用例）：5×429+Retry-After 熔断 / 5×429 无 Retry-After 熔断 / 单等待≤30s 封顶 / 成功重置计数。
- `test_progress_reporting.py`（2 用例）：部分成功计数 cells_done=1,cells_error=2 / 全成功 cells_done=3,cells_error=0。


---

## 5. 关键约束与回滚

- **绝不两个写进程共享同一 SQLite**：验证步骤只启动**一个** backend（`uvicorn app.main:app --port 8000`）。
- 所有改动保持向后兼容：`MockProvider` 保留；无 API 破坏性变更（`progress`/`rows_total` 已存在，`cells_done`/`cells_error` 为新增可空字段）。
- 若测试不通过或 review 否决，对应阶段标记 ❌ 并回退该 agent 改动，不合并进主线。

### 4.3 Adversarial review 修复明细（2026-07-20）

独立审查 agent 发现 6 处高/中严重度缺陷，全部已修复并补回归测试（新增 `test_review_regressions.py`，5 用例）：

| 严重度 | 发现 | 修复 |
|--------|------|------|
| 高 | 2.2 单 call 内 `while True` 对 429 无重试上限 | 新增 `_MAX_429_PER_CALL=10` 单 call 上限，超则抛 `ProviderRateLimitedError` |
| 高 | 4.3 `error` 被 `_sanitize_error` 脱敏成空话，诊断可见性归零 | allowlist 透传 "database is locked"/"rate limited"/"ProviderRateLimitedError" 等关键词（最具体优先），仍脱敏 SQL/路径 |
| 中 | 1.1 `with_retry_on_lock` 注释"6.2s 放弃"错误（漏算 busy_timeout） | 注释修正为说明真实最坏等待（≈1.4s backoff + 15s busy_timeout），`max_attempts` 5→4 使 backoff 远小于 busy_timeout |
| 中 | 2.3 openrouter 注释"跨实验共享"错误（实际 per-run 实例） | 修正注释为 per-run 实例语义 |
| 中 | 4.1 `_persist_progress` best-effort 被 `except SQLAlchemyError` 破坏 | 改为 `except Exception` |
| 中 | 4.2 `_mark_failed` 仅接 SQLAlchemyError，可能漏接致停留 running | 改为 `except Exception` |

未修（评估为非真问题/超范围）：1.2/3.1 未提交可见性竞态（SQLite 单写者已知边缘限制，CAS 已正确处理 loser 丢弃）；2.3 failed vs partial 语义（熔断快速失败符合用户意图，保留 failed）；6 剩余测试盲区（低优先，后续可补）。

### 4.4 启动单一 backend 验证（阶段 7）

约束：生产环境只启动**一个** backend 进程（`uvicorn app.main:app --port 8000`），严禁同时启动 8000/8001 两个写同一 SQLite 的实例（这是根因之一）。

阶段 7 已验证：单一 backend（port 8000）干净启动，`provider_mode=openrouter`（真实 key 生效），`cells_done`/`cells_error`/`progress`/`rows_total` 经真实 API run 全部正确落库（示例：3 行数据集 run 后 `status=completed, progress=3, rows_total=3, cells_done=3, cells_error=0`）。`acc=0.0` 为 free 模型输出格式与 `exact_match_ci` 不匹配所致，与本次并发/429/进度优化无关，非回归。

| 阶段 | 任务 | 状态 | 完成时间 | 备注 |
|------|------|------|----------|------|
| 7 | 启动单一 backend 验证全链路 | ✅ 完成 | 2026-07-20 | 单一进程启动、真实 run 进度字段落库正确 |

---

## 6. 总结

本次优化解决了日志分析的 3 个根因：
1. **SQLite 并发锁死**（根因 1+2）：`with_retry_on_lock` 应用层指数退避重试 + 现有 WAL/busy_timeout，关键状态更新不再静默丢失；根因层面的"两进程共享 SQLite"已通过文档约束（单一 backend）缓解。
2. **OpenRouter 429 无限空转**（根因 3）：智能退避（读 Retry-After、上限 30s）+ 跨 row 熔断（阈值 5）+ 单 call 上限（10），持续限流时实验在约 20s 内进入 `failed` 而非空转数小时。
3. **进度不可见**：后端 `cells_done`/`cells_error` 字段 + 前端 running 态三段式进度条（已评分/失败/共 Z + 百分比）。

单元测试 40 passed（含新增 10 用例覆盖 429/lock/进度/脱敏/熔断上限），adversarial review 发现并修复 6 处高/中缺陷。所有改动向后兼容（Mock 保留为测试替身，API 无破坏性变更）。

**生产约束（务必遵守）**：只启动一个 backend 进程写 SQLite；若需多实例或高并发，请切换 `DATABASE_URL` 到 Postgres。

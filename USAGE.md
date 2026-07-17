# BenchmarkOps 用户使用说明

> 面向使用者与开发者的上手与功能说明文档。项目建设代码位于本仓库 `backend/`（FastAPI）与 `frontend/`（Next.js）两个目录，本文档的命令路径与配置项均对照实际代码核实。

---

## 1. 项目简介

**BenchmarkOps** 是一个企业级 **AI 评测 / 基准运维（Evaluation & Benchmark Operations）平台**，用于围绕统一的评测工作流管理数据集、基准、提示词、模型、实验、分析与报告。

### 核心工作流

```
Project → Dataset → Benchmark → Prompt → Model → Experiment → Run → Compare → Report
```

1. **Project（项目）**：评测活动的最外层容器，所有其它资源按项目归属。
2. **Model（模型）**：统一模型注册表，记录 provider、定价、上下文长度与能力标签。
3. **Dataset（数据集）**：上传的评测样例（JSONL/JSON/CSV），每行含输入与期望输出。
4. **Benchmark（基准）**：定义评测协议——类型（qa/coding/agent…）与评分指标。
5. **Prompt（提示词）**：可复用模板，使用单花括号变量占位符（如 `{question}`）。
6. **Experiment（实验）**：把「数据集 + 基准 + 提示词 + 模型」绑定成一次评测任务。
7. **Run（运行）**：执行实验，逐行调用模型并打分，记录准确率 / 延迟 / 花费。
8. **Compare（对比）**：横向对比多个已完成实验的准确率、延迟、花费、令牌数。
9. **Report（报告）**：基于实验生成结构化 Markdown 报告（模板报告 / AI 报告），可导出。

平台另提供 **仪表盘（Dashboard）**、**行业雷达（Industry Radar）** 和 **设置（Settings）** 三个聚合视图，便于总览与运维。

---

## 2. 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Next.js 16（App Router，v16.2.10）· React 19（19.2.4）· TypeScript 5 · Tailwind CSS v4 · 手写 SVG 图表 · lucide-react（图标） |
| 后端 | FastAPI · SQLAlchemy 2.0（async）· Pydantic v2 / pydantic-settings · uvicorn |
| 数据库 | SQLite（v1，默认 `sqlite+aiosqlite:///./benchmarkops.db`），可切换为 PostgreSQL |
| Provider | OpenRouter 单网关；未配置 Key 时自动回退到确定的 **Mock Provider**（合成结果，可离线跑通） |
| Runner | v1 进程内线程任务队列（in-process threaded task queue）；后续迭代计划接入 Celery |

**架构**：Clean Architecture，严格分层 `Router（薄层）→ Service（业务逻辑）→ Repository（数据访问）→ ORM`。Router 不触碰 ORM；Service 仅依赖 Repository 抽象；Provider 注册表可插拔（新增 provider / 指标 / 模块 = 新增文件，不改既有逻辑）。评测引擎依赖 `TaskQueue` 抽象。

---

## 3. 环境要求

- **Python**：≥ 3.11（`pyproject.toml` 中 `requires-python = ">=3.11"`）。
- **Node.js**：≥ 18（建议 20+，`@types/node` 为 `^20`）。`package.json` 未声明 `engines`，但 Next.js 16 需现代 Node 版本。
- **包管理器**：
  - 后端使用 **uv**（Python 包 / 虚拟环境管理）。
  - 前端使用 **npm**（或 yarn / pnpm / bun，脚本等价）。
- **操作系统**：跨平台（Windows / macOS / Linux 均可，已用 `aiosqlite` 异步驱动）。

---

## 4. 快速开始

### 4.1 启动后端

```bash
cd backend
cp .env.example .env          # 可选：设置 OPENROUTER_API_KEY、API_TOKEN 等
uv venv --python 3.11
uv pip install -e ".[dev]"
uv run uvicorn app.main:app --reload --port 8000
```

启动后可访问：

- API 交互文档：**http://localhost:8000/docs**（Swagger UI）
- 健康检查：**http://localhost:8000/api/v1/health**

> 不配置 `OPENROUTER_API_KEY` 时，Provider 自动走 Mock，所有功能可离线使用。
> 数据库文件 `benchmarkops.db` 会在首次启动时在 `backend/` 下自动创建。

### 4.2 启动前端

```bash
cd frontend
cp .env.local.example .env.local   # 设置 NEXT_PUBLIC_API_BASE_URL
npm install
npm run dev
```

启动后访问 **http://localhost:3000**。

`.env.local` 关键项（见 `frontend/.env.local.example`）：

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
```

### 4.3 灌入 Demo 数据

后端就绪后，另开一个终端：

```bash
cd backend
uv run python -m app.seed
```

该命令通过真实 API 层（`TestClient`）端到端构建一套可运行的 Demo：

- 创建一个项目 **`Demo: QA Benchmark`**；
- 调用 `POST /models/seed` 灌入 **8 个模型**（含 Claude 3.5 Haiku、GPT-4o mini 等）；
- 上传一个 **QA 算术数据集**（JSONL，5 行，确保 Mock Provider 在 `exact_match` 上得满分）；
- 建一个基准 **QA Exact Match**（类型 `qa`，指标 `exact_match`）；
- 写一个提示词 **Answer directly**（模板 `Question: {question}\nAnswer with only the final result.`）；
- 在 **Claude 3.5 Haiku** 与 **GPT-4o mini** 两个模型上各跑 **1 个实验**（共 2 个）；
- 自动执行 **对比（compare）** 与生成一份 **报告（report）**。

灌完后打开前端 → 进入 **Demo: QA Benchmark** 项目，查看 **对比（Compare）** 与 **报告（Reports）** 即可。

---

## 5. 核心功能使用（按工作流顺序）

> 以下操作均在浏览器 `http://localhost:3000` 完成。多数写操作在 `API_TOKEN` 留空时不需鉴权；配置 token 后需带 `Authorization: Bearer <token>`（前端暂未内置 token 输入，生产环境需另行接入）。

### 步骤 1：建项目
- 进入 **仪表盘**（首页）→ 点右上角「新建项目」，或到 **Projects** 页面创建。
- 填写名称与描述，状态默认为 `active`。
- 项目详情页（`/projects/[id]`）用标签页组织该项目下的「数据集 / 基准 / 提示词 / 实验 / 报告」。

### 步骤 2：加模型
- 进入 **Models（模型中心）** 页面 → 点「初始化模型」会调用 `POST /models/seed` 灌入 8 个常用模型。
- 模型卡片展示 provider、上下文长度、输入/输出定价（每 1K 令牌 USD）、能力标签与启用状态。
- （也可通过「模型中心」或 API 手动新增单个模型。）

### 步骤 3：上传数据集
- 进入 **Datasets（数据集）** 页面 → 点「上传数据集」。
- 选择所属项目、选择文件（支持 **JSONL / JSON / CSV**，扩展名自动识别格式）、填写名称与描述。
- **格式**：每行一个 JSON 对象，至少含输入与期望输出字段，例如：
  ```json
  {"question": "Compute 2 + 2.", "answer": "4"}
  ```
- 上传限制：**单文件 ≤ 50 MB，行数 ≤ 100,000 行**（超过将被拒绝，见 §6）。
- 上传后可在列表「预览」查看前若干行（输入 / 期望）。

### 步骤 4：建基准
- 进入 **Benchmarks（基准）** 页面 → 点「新建基准」。
- 选择所属项目、填写名称、**类型** 与 **指标**：
  - 类型：`qa` / `coding` / `agent` / `classification` / `generation`
  - 指标（部分默认映射）：`exact_match`、`exact_match_ci`、`contains`、`f1_token`、`numeric_match`；各类型默认指标为 qa→`exact_match_ci`、classification→`exact_match_ci`、coding→`contains`、generation→`f1_token`、agent→`contains`。
- 可在基准页「指标」下拉中看到后端 `GET /benchmarks/metrics/available` 返回的全部可用指标。

### 步骤 5：写提示词
- 进入 **Prompts（提示词库）** 页面 → 点「新建提示词」。
- 填写所属项目、名称、模板与描述。
- **模板变量用单花括号占位符**：如 `Question: {question}\nAnswer with only the final result.`，运行时由数据集字段填充。
- 提示词按 `(project_id)` 隔离，有版本号（`v1`…）。

### 步骤 6：建实验并运行
两种入口：

- **评测向导（Evaluation 页面）**：引导式 5 步——选择项目 → 数据集 → 基准 → 提示词 → 模型，最后点「运行评测」自动创建实验并触发运行。
- **实验列表 / 项目详情「实验」标签**：手动创建实验后点「运行」。

运行后：
- 评测向导与实验详情页都会**轮询运行状态**（向导每 1.5s、详情页每 1.0s），运行中显示「运行中… 正在轮询实验状态」与进度；状态变为 `completed` / `failed` / `partial` 后停止轮询。
- 实验详情页（`/experiments/[id]`）展示准确率、花费、令牌数、运行耗时等卡片，以及**逐行结果表**（输入 / 期望 / 输出 / 得分 / 延迟 / 令牌数 / 花费）。

### 步骤 7：对比实验
- 进入 **Compare（对比实验）** 页面（`/experiments/compare`）。
- 从「已完成实验」中勾选 ≥ 2 个，页面以柱状图对比 **准确率(%) / 平均延迟(ms) / 总花费(USD) / 总令牌数**，并展示 **排行榜** 表格（实验、模型、准确率、花费、延迟、令牌数）。

### 步骤 8：生成报告
- 进入 **Reports（AI 报告）** 页面 → 点「生成报告」。
- 选择项目、填写可选标题、勾选要纳入的实验，点「生成」。
- **报告类型**：配置了 `OPENROUTER_API_KEY` 时优先生成 **AI 报告**（调用 provider，默认模型 `openai/gpt-4o-mini`）；未配置或 provider 调用失败则自动回退 **模板报告**（确定性 Markdown，零 LLM 依赖）。
- **导出**：在报告卡片点「导出」，前端通过 `GET /reports/{report_id}/export` 下载 `.md` 文件（文件名取报告标题，空格替换为下划线）。

### 步骤 9：行业雷达（Industry Radar）
- 已有独立页面 `/industry-radar`（并非仅计划项，已实现）。
- 汇总全部实验与模型的整体洞察：KPI（实验总数、平均准确率、对比模型数、总花费）、**各供应商准确率雷达图**、实验状态环图、各模型准确率柱状图与排行榜。

---

## 6. 配置说明

后端配置全部来自环境变量 / `.env`（`backend/.env`），由 `app/core/config.py`（pydantic-settings）读取，**无硬编码值**。

### 6.1 `backend/.env` 关键配置项

> 表中「默认值」为 `config.py` 中的定义。注意：当前仓库 `backend/.env.example` **未包含** `API_TOKEN`、`MAX_UPLOAD_BYTES`、`MAX_DATASET_ROWS` 三项（见 §10 不一致说明），如需生效请手动在 `.env` 中补充。

| 配置项 | 默认值 | 含义 / 何时修改 |
|--------|--------|----------------|
| `APP_NAME` | `BenchmarkOps` | 应用名（问候/标题用）。一般不必改。 |
| `APP_ENV` | `development` | 运行环境标识，会出现在 `/health`。 |
| `API_V1_PREFIX` | `/api/v1` | API 基础路径前缀。一般不必改。 |
| `API_TOKEN` | _（空）_ | 全局写操作鉴权 token。**留空 = 不强制鉴权**（Demo / Mock 模式）；配置后所有写请求需 `Authorization: Bearer <token>`，读写分离：GET / health / analytics / compare 等读接口仍开放。生产环境建议设置。 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./benchmarkops.db` | 数据库连接串。**切换 Postgres** 时改为如 `postgresql+asyncpg://user:pass@host/db`。 |
| `BACKEND_CORS_ORIGINS` | `http://localhost:3000,http://localhost:3001,http://localhost:3002` | 允许的浏览器来源（逗号分隔）。换前端端口 / 域名时必须同步更新，否则跨域被拒。 |
| `OPENROUTER_API_KEY` | _（空）_ | OpenRouter 网关密钥。**留空走 Mock Provider**；填入即启用真实模型（`provider_enabled=True`）。 |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter API 地址。一般不必改。 |
| `OPENROUTER_HTTP_REFERER` | `http://localhost:3000` | 上报给 OpenRouter 的 referer。部署时改为前端域名。 |
| `OPENROUTER_APP_TITLE` | `BenchmarkOps` | 上报给 OpenRouter 的应用名。 |
| `EVAL_MAX_WORKERS` | `4` | 评测并发 worker 数。**当前未用于并发控制**（v1 为进程内线程队列，预留项）。 |
| `EVAL_REQUEST_TIMEOUT` | `60` | 单次模型请求超时（秒）。真实 provider 下可调大以应对慢模型。 |
| `MAX_UPLOAD_BYTES` | `52428800`（50 MB） | 数据集上传字节上限，超出在读取阶段即拒绝。按服务器内存调整。 |
| `MAX_DATASET_ROWS` | `100000` | 数据集行数上限，超出在解析阶段即拒绝。 |

### 6.2 鉴权机制说明（基于 `app/core/security.py`）

- `require_auth` 依赖挂在**所有写端点**（POST / PATCH / DELETE、以及 `POST /analytics/compare`、`POST /reports/generate` 等）。
- `api_token` 为空 → 直接放行（Demo / Mock 模式）。
- `api_token` 非空 → 要求 `Authorization: Bearer <token>`；缺失或错误返回 401。
- 这是**单 token 简化鉴权**，并非完整用户/租户系统（详见 §9 限制）。

### 6.3 前端配置（`.env.local`）

| 配置项 | 默认值 | 含义 |
|--------|--------|------|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000/api/v1` | 前端调用的后端 API 基址。后端换端口/域名时必须同步修改。 |

---

## 7. API 概览

- **基础路径**：`/api/v1`（由 `API_V1_PREFIX` 定义）。
- **文档**：Swagger UI 在 `/docs`，OpenAPI JSON 在 `/openapi.json`。
- 主要分组（对应 `backend/app/api/v1/routes/*.py`，统一在 `router.py` 注册）与写操作的鉴权（`require_auth`）情况：

| 分组 | 路径前缀 | 主要端点 | 鉴权 |
|------|----------|----------|------|
| health | `/health` | `GET /health` | 否 |
| projects | `/projects` | `POST /` `GET /` `GET /{id}` `PATCH /{id}` `POST /{id}/archive` `DELETE /{id}` | 写需 token |
| models | `/models` | `POST /` `GET /` `GET /{id}` `PATCH /{id}` `DELETE /{id}` `POST /seed` | 写需 token |
| datasets | `/datasets` | `POST /upload` `GET /` `GET /{id}` `GET /{id}/preview` `GET /{id}/stats` `POST /{id}/validate` `PATCH /{id}` `DELETE /{id}` | 写需 token |
| prompts | `/prompts` | `POST /` `GET /` `GET /{id}` `PATCH /{id}` `DELETE /{id}` `POST /{id}/render` | 写需 token |
| benchmarks | `/benchmarks` | `POST /` `GET /` `GET /metrics/available` `GET /{id}` `PATCH /{id}` `DELETE /{id}` | 写需 token |
| experiments | `/experiments` | `POST /` `GET /` `GET /{id}` `GET /{id}/results` `PATCH /{id}` **`POST /{id}/run`** `POST /{id}/retry` `POST /{id}/duplicate` `DELETE /{id}` | 写需 token |
| analytics | `/analytics` | `GET /leaderboard` **`POST /compare`** `GET /experiments/{id}/failures` `GET /trend` `GET /projects/{id}/summary` | 否（读接口） |
| reports | `/reports` | **`POST /generate`** `GET /` `GET /{id}` `GET /{id}/export` `DELETE /{id}` | 生成/删除需 token；读取/导出否 |

### 关键示例

```bash
# 健康检查（含 provider 模式）
curl http://localhost:8000/api/v1/health

# 运行某个实验（触发评测）
curl -X POST http://localhost:8000/api/v1/experiments/{experiment_id}/run

# 对比多个实验
curl -X POST http://localhost:8000/api/v1/analytics/compare \
  -H "Content-Type: application/json" \
  -d '{"experiment_ids": ["<id1>", "<id2>"]}'

# 上传数据集（multipart）
curl -X POST http://localhost:8000/api/v1/datasets/upload \
  -F "file=@qa.jsonl" \
  -F "project_id=<project_id>" \
  -F "name=QA Sample" \
  -F "format=jsonl"
```

> 配置 `API_TOKEN` 后，上述写操作需加 `-H "Authorization: Bearer <token>"`。

---

## 8. 开发说明（简要）

### 8.1 数据库迁移

采用**零依赖的轻量迁移机制**（`backend/app/migrations/__init__.py`），替代 Alembic：

- 基线结构由 SQLAlchemy `create_all` 建立（启动时自动执行）。
- 框架表 `schema_version` 用原生 `conn.execute` 管理，**不注册在 ORM `Base` 上**，故 `create_all` 不会触碰它。
- 迁移是形如 `async def upgrade(conn)` 的协程，注册在 `MIGRATIONS` 字典中，键为递增的整数版本号。
- `run_migrations` **幂等**：已记录版本（在 `schema_version` 中）会被跳过，可每次启动调用、调用两次也安全。

**开发者新增迁移步骤**（参考现有 `v10` 示例 `_upgrade_experiment_snapshot_and_metrics`）：

1. 写一个升级函数，用原生连接做 ALTER（建表 / 加列 / 改类型 / 建索引），最好做「列已存在则跳过」的防护：

   ```python
   async def upgrade_add_foo(conn) -> None:
       await conn.execute(sa.text("ALTER TABLE bar ADD COLUMN foo TEXT"))
   ```

2. 在 `MIGRATIONS` 中以「下一个版本号」登记：

   ```python
   MIGRATIONS[11] = upgrade_add_foo
   ```

3. 重启后端，迁移自动应用（已应用版本不再重复）。

### 8.2 测试

```bash
cd backend
uv run pytest
```

配置见 `pyproject.toml`：`asyncio_mode = "auto"`，测试目录 `tests`。

### 8.3 架构与扩展点

- 分层：`Router（薄）→ Service（业务）→ Repository（数据）→ ORM`；Router 不直连 ORM。
- **Provider 可插拔**：通过 `app/providers/registry.py` 的注册表切换；实现 `get_provider()`、`active_provider_name()`，新增网关只需新文件。
- **指标可插拔**：`app/evaluation/metrics.py` 用 `@register("name")` 装饰器注册纯函数 `(prediction, expected, **kwargs) -> float`，返回 `[0,1]`。
- **评测引擎**依赖 `TaskQueue` 抽象（v1 为进程内实现），与具体队列实现解耦，便于后续接入 Celery。

---

## 9. 已知限制 / 后续规划

### 当前阶段（v1，单人 Demo 级）

- **鉴权为单 token 简化**：`api_token` 是全局共享密钥，非用户/租户系统；读取接口默认开放。生产部署需补充完整身份与多租户方案。
- **无多租户 / 无组织隔离**：所有项目共享同一数据库与同一 token 空间。
- **评测为进程内执行**：`EVAL_MAX_WORKERS` 当前**并未用于并发控制**；同一进程内的线程队列串行/有限并行执行，进程重启会中断进行中的运行。
- **数据集存储**：上传文件内容以原始字节存入数据库（非对象存储），受 `MAX_UPLOAD_BYTES` / `MAX_DATASET_ROWS` 保护。
- **报告导出**：仅 Markdown（`.md`）下载，无 PDF / HTML 等格式。

### 预留 / 后续迭代（README 中 "Reserved for later iterations"）

- **Redis**：作为缓存 / 队列后端。
- **Celery**：替代进程内线程队列，支持分布式、可恢复的任务执行。
- **MinIO**：对象存储，替代数据库内联存数据集。
- **multi-Agent layer**：更复杂的评测 / 报告生成智能体层。

---

## 10. README 与实现不一致之处（核对发现）

文档编写时对照实际代码，发现以下 README / 示例与实现的差异：

1. **Industry Radar 已实装**：README 的 "Reserved..." 段落容易让人以为 Industry Radar 是后续项，但前端已有完整页面 `/industry-radar`（行业雷达 KPI、供应商雷达图、状态环图、排行），并非仅规划。
2. **`backend/.env.example` 遗漏三项配置**：`config.py` 已定义 `API_TOKEN`、`MAX_UPLOAD_BYTES`（50 MB）、`MAX_DATASET_ROWS`（100,000），但仓库 `backend/.env.example` 中**只有** APP / DATABASE / CORS / OpenRouter / EVAL 几项，未列出这三项。文档 §6.1 已据 `config.py` 补全默认值；如需生效请在 `.env` 手动添加。
3. **`API_TOKEN` 鉴权为新增机制**：README 未提及鉴权，实际 `security.py` 已实现「空 token 不强制、配了则需 Bearer」的单 token 方案，并挂在全部写端点。
4. **`EVAL_MAX_WORKERS` 当前未生效**：README 与 config 注释均标注其为并发 worker，但代码中仅作为配置项存在，v1 运行器为进程内线程队列、未真正用于并发控制（已据注释在 §6.1、§9 说明）。
5. **前端 `AGENTS.md` 提示 Next.js 16 有破坏性变更**：next 16.2.10 与训练数据中的 Next.js 约定可能不同，前端开发前应阅读 `node_modules/next/dist/docs/`。
6. **报告同时支持 AI 与模板两种模式**：README 仅概括为 "AI Reports"，实际 `report_service.py` 在配置 key 时走 AI 报告、否则（或失败）确定性回退模板报告。

> 本文档未修改任何源码或示例文件，仅新增本说明。

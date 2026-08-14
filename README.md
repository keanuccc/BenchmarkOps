<div align="right">

[English](README.en.md) | **简体中文**

</div>

# BenchmarkOps

<div align="center">

**企业级 AI 评测与基准运维平台**（Enterprise AI Evaluation & Benchmark Operations Platform）

[![Backend Tests](https://github.com/keanuccc/BenchmarkOps/actions/workflows/backend-tests.yml/badge.svg)](https://github.com/keanuccc/BenchmarkOps/actions/workflows/backend-tests.yml)
[![Frontend E2E](https://github.com/keanuccc/BenchmarkOps/actions/workflows/e2e.yml/badge.svg)](https://github.com/keanuccc/BenchmarkOps/actions/workflows/e2e.yml)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

BenchmarkOps 是一个围绕**统一评测工作流**管理数据集、基准、提示词、模型、实验、分析与报告的企业级平台，核心流程如下：

```mermaid
flowchart LR
    A[Project 项目] --> B[Dataset 数据集]
    B --> C[Benchmark 基准]
    C --> D[Prompt 提示词]
    D --> E[Model 模型]
    E --> F[Experiment 实验]
    F --> G[Run 运行]
    G --> H[Compare 对比]
    H --> I[Report 报告]
```

简单说，它把“跑一次模型评测”从脚本散落、结果难比的状态，变成一条**可复现、可审计、可对比**的标准化流水线。

### 主要亮点

- **开箱即用**：未配置任何 API Key 时自动使用 Mock Provider，全部功能可离线演示
- **结果可复现**：实验创建时快照模型 Provider、数据集版本与提示词版本
- **可插拔架构**：新增 Provider / 评测指标 / 业务模块只需新增文件，无需改动既有逻辑
- **双队列支持**：进程内 asyncio 队列（默认）与 Redis + ARQ 分布式队列（可选）
- **CI 覆盖**：后端单元测试与前端 Playwright E2E 已接入 GitHub Actions

## 演示

<video src="videos/benchmarkops-demo/my-video/renders/benchmarkops-demo-v2.mp4" controls width="100%"></video>

![总览看板](videos/benchmarkops-demo/my-video/capture/screenshots/full-page.png)

## 真实评测结果

项目内置**真实公开数据集 + 真实模型**的跨网关评测（详见
[docs/real-world-eval/](docs/real-world-eval/)），覆盖：

- **C-Eval**：中文考试真题问答（60+ 题，选项精确匹配）
- **THUCNews**：新闻文本分类（10 类）
- **HumanEval**：Python 代码生成

模型同时路由到**七牛云 AI** 与 **OpenRouter** 两个网关，验证平台的多 Provider
可插拔架构。评测方法与一键复现脚本见
[sample-data/real-world/README.md](sample-data/real-world/README.md)，
评测报告见 [docs/real-world-eval/report.md](docs/real-world-eval/report.md)，
深度分析见 [docs/real-world-eval/ANALYSIS.md](docs/real-world-eval/ANALYSIS.md)。

**最近一次评测结果（2026-08-14，真实模型、真实数据、七牛网关、全量样本）**：

| 模型 | C-Eval 问答 | THUCNews 分类 | HumanEval 代码 |
|---|---:|---:|---:|
| DeepSeek V4 Flash | **86.89%** | **89.17%** | 95.00% |
| DeepSeek V3 | 70.49% | 84.17% | **100.00%** |

> 样本量：C-Eval 61 / THUCNews 120 / HumanEval 60，总成本 $0（七牛免费额度）。
> 统计显著性分析见 [docs/real-world-eval/significance.md](docs/real-world-eval/significance.md)：
> C-Eval 上 V4 Flash 显著领先（p=0.007），THUCNews 与 HumanEval 上差异不显著
> （p 分别为 0.069 / 0.068）——中文问答优先 V4 Flash，其余场景两模型接近。

## 目录

- [功能特性](#功能特性)
- [演示](#演示)
- [真实评测结果](#真实评测结果)
- [技术栈](#技术栈)
- [架构](#架构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [项目结构](#项目结构)
- [测试与 CI](#测试与-ci)
- [API 概览](#api-概览)
- [相关文档](#相关文档)
- [已知限制与注意事项](#已知限制与注意事项)
- [路线图](#路线图)
- [贡献](#贡献)
- [License](#license)

## 功能特性

| 模块 | 说明 |
|------|------|
| **项目管理** | 创建、归档项目，所有资源按项目隔离 |
| **模型中心** | 统一模型注册表，支持多 Provider（DeepSeek 直连 / Qiniu AI / OpenRouter / Mock），含定价与能力标签 |
| **数据集** | 上传 JSONL / JSON / CSV / TSV / XLSX 评测样例，支持预览、校验、版本化、异步导入、敏感字段脱敏与审计 |
| **基准（Benchmarks）** | 定义评测协议（qa / coding / agent / classification / generation），内置多种评分指标 |
| **提示词库** | 可复用模板，支持 `{variable}` 占位符（含嵌套路径寻址），版本化管理 |
| **实验运行** | 绑定数据集 + 基准 + 提示词 + 模型，异步执行评测，实时进度轮询；创建时保存模型 Provider 与免费模型状态快照 |
| **对比分析** | 柱状图对比多个实验的准确率、延迟、花费、令牌数 |
| **统计显著性** | A/B 模型对比的 bootstrap 置信区间、配对检验与 McNemar 检验 |
| **LLM-judge 校准** | 对照 gold set 的 precision/recall/F1 校准，以及 Cohen's kappa 一致性检验 |
| **代码执行沙箱** | coding 评测真实执行代码，拦截危险模块导入并隔离运行环境 |
| **AI 报告** | 基于实验结果生成结构化 Markdown 报告，支持 AI 生成或确定性模板回退，并可导出 PDF |
| **仪表盘** | 总览项目、实验状态、准确率趋势、模型排行榜 |
| **行业雷达** | 汇总全部实验与模型的整体洞察：KPI、供应商准确率雷达图、状态环图 |

## 技术栈

| 层 | 技术 |
|----|------|
| **前端** | Next.js 14（App Router）· React 18 · TypeScript · Tailwind CSS v4 · ECharts · lucide-react |
| **后端** | FastAPI · SQLAlchemy 2.0（async）· Pydantic v2 · uvicorn |
| **数据库** | SQLite（aiosqlite，默认）→ 可切换 PostgreSQL（postgresql+asyncpg） |
| **LLM Provider** | DeepSeek 官方直连（默认）· Qiniu AI · OpenRouter · Mock（离线回退）；实验快照固定实际 Provider 路由 |
| **任务队列** | 进程内 asyncio（默认）· Redis + ARQ 分布式队列（可选），支持并发限制、取消、任务持久化与崩溃恢复 |
| **测试 / CI** | pytest · Playwright · GitHub Actions |

## 架构

后端采用 **Clean Architecture** 严格分层：`Router（薄层）→ Service（业务逻辑）→ Repository（数据访问）→ ORM`。Provider 注册表可插拔，新增 provider / 指标 / 模块只需新增文件。

```mermaid
flowchart TB
    subgraph FE["Frontend (Next.js 14)"]
        UI["React UI / ECharts"]
        CLIENT["API Client"]
    end
    subgraph BE["Backend (FastAPI)"]
        ROUTER["API Router"]
        SERVICE["Service Layer"]
        REPO["Repository Layer"]
        ORM["SQLAlchemy 2.0 ORM"]
        EVAL["Evaluation Engine"]
        QUEUE["Task Queue<br/>asyncio / ARQ"]
    end
    subgraph STORE["Storage"]
        DB[("SQLite / PostgreSQL")]
        REDIS[("Redis（ARQ 可选）")]
    end
    subgraph LLM["LLM Providers"]
        P0["DeepSeek（直连）"]
        P1["OpenRouter"]
        P2["Qiniu AI"]
        P3["Mock"]
    end

    UI --> CLIENT
    CLIENT --> ROUTER
    ROUTER --> SERVICE
    SERVICE --> REPO
    REPO --> ORM
    ORM --> DB
    SERVICE --> EVAL
    EVAL --> QUEUE
    QUEUE --> REDIS
    EVAL --> P0 & P1 & P2 & P3
```

## 快速开始

### 环境要求

- **Python** ≥ 3.11
- **Node.js** ≥ 18（推荐 20+）
- **uv** — Python 包管理器（[安装指南](https://docs.astral.sh/uv/getting-started/installation/)）
- **npm** — Node 包管理器
- （可选）**Docker** — 用于一键启动

### 方式一：本地开发

#### 1. 启动后端

```bash
cd backend

# 复制配置
cp .env.example .env

# 创建虚拟环境并安装依赖
uv venv --python 3.11
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"

# 启动服务
uv run uvicorn app.main:app --reload --port 8000
```

后端就绪后可访问：

- API 文档（Swagger UI）：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/v1/health

#### 2. 启动前端

```bash
cd frontend

# 复制配置
cp .env.local.example .env.local

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端就绪后访问 http://localhost:3000。

#### 3. 灌入 Demo 数据（可选）

```bash
cd backend
uv run python -m app.seed
```

自动创建一套完整 Demo：项目、8 个模型、数据集、基准、提示词、2 个实验及报告。打开前端进入 **Demo: QA Benchmark** 项目即可查看。

> 💡 未配置 `DEEPSEEK_API_KEY` / `QINIU_API_KEY` / `OPENROUTER_API_KEY` 时，评测自动走 **Mock Provider**，无需联网即可体验完整流程。

### 方式二：Docker Compose 一键启动

```bash
docker compose up --build
```

该 Compose 包含 Redis 与 ARQ worker：

- 前端：http://localhost:3000
- 后端：http://localhost:8000

### 生产部署

生产环境使用 PostgreSQL + Redis/ARQ + 独立 worker 的部署形态，参见 [docs/docker-deployment.md](docs/docker-deployment.md)。

## 配置说明

### 后端 `.env`（模板见 `backend/.env.example`）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `API_TOKEN` | *(空)* | 全局鉴权 token。留空 = 不强制鉴权（Demo/Mock 模式）；配置后所有写请求需 `Authorization: Bearer <token>` |
| `APP_ENV` | `development` | 置为 `production` 时若未设置 `API_TOKEN`，应用拒绝启动 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./benchmarkops.db` | 数据库连接串，生产环境建议切换 PostgreSQL |
| `DEFAULT_PROVIDER` | `deepseek` | 默认 Provider 路由，可选 `deepseek` / `openrouter` / `qiniu` / `mock` |
| `DEEPSEEK_API_KEY` | *(空)* | DeepSeek 官方 API 密钥（国产、低成本、默认直连）；留空自动走 Mock Provider |
| `OPENROUTER_API_KEY` | *(空)* | OpenRouter API 密钥；留空自动走 Mock Provider，可离线使用 |
| `QINIU_API_KEY` | *(空)* | 七牛云 AI Token API 密钥 |
| `BACKEND_CORS_ORIGINS` | `http://localhost:3000,...` | 允许的浏览器来源，换端口/域名时必须同步更新 |
| `TASK_QUEUE_BACKEND` | `asyncio` | 任务队列后端：`asyncio`（进程内，默认）或 `arq`（Redis 分布式队列） |
| `REDIS_DSN` | `redis://localhost:6379/0` | ARQ 队列与 worker 使用的 Redis 连接串（仅 `arq` 模式） |
| `EVAL_MAX_WORKERS` | `4` | 单 worker 进程内的评测并发上限 |
| `TASK_MAX_TRIES` | `2` | 单任务最大尝试次数；仅瞬态、计费前失败会重试，Provider 侧失败不重试 |
| `REPORT_MODEL_ID` | *(空)* | AI 报告生成模型；留空按网关使用内置默认（DeepSeek 为 `deepseek-chat`） |
| `MAX_UPLOAD_BYTES` | `52428800` (50 MB) | 数据集上传大小上限 |
| `MAX_DATASET_ROWS` | `100000` | 数据集行数上限 |

### 前端 `.env.local`（模板见 `frontend/.env.local.example`）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000/api/v1` | 前端调用的后端 API 基址 |

## 项目结构

```text
backend/
├── app/
│   ├── api/v1/routes/      # API 路由层
│   ├── core/               # 配置、数据库、安全、异常处理
│   ├── evaluation/         # 评测引擎：runner、metrics、task queue
│   ├── providers/          # LLM Provider 注册表（可插拔）
│   ├── repositories/       # 数据访问层（Repository 抽象）
│   ├── services/           # 业务逻辑层
│   ├── models/             # ORM 模型
│   ├── schemas/            # Pydantic 模型
│   ├── report/             # 报告生成（AI / 模板 / PDF）
│   └── migrations/         # 数据库迁移
frontend/
├── src/
│   ├── app/                # Next.js App Router 页面
│   ├── components/         # React 组件（UI / 图表 / 布局）
│   └── lib/                # API 客户端、工具函数
```

## 测试与 CI

```bash
cd backend
uv run pytest              # 单元测试（默认排除 e2e）
uv run pytest -m e2e       # 端到端测试（需网络）

cd ../frontend
npm run lint               # ESLint 检查
npm run build              # Next.js 生产构建
```

当前基线：后端 pytest 全量通过（`334 passed, 7 skipped`），前端 TypeScript、lint 和生产构建均已通过。

仓库内置两个 GitHub Actions 工作流：

- **Backend Tests**：push / PR 时自动运行后端单元测试
- **Frontend E2E**：启动前后端后运行 Playwright 端到端测试

## API 概览

所有 API 端点在 `/api/v1` 下，完整交互式文档见 `/docs`（Swagger UI）。

| 分组 | 路径 | 鉴权 |
|------|------|------|
| Health | `GET /health` | 否 |
| Projects | `/projects/*` | 写需 token |
| Models | `/models/*` | 写需 token |
| Datasets | `/datasets/*` | 写需 token |
| Benchmarks | `/benchmarks/*` | 写需 token |
| Prompts | `/prompts/*` | 写需 token |
| Experiments | `/experiments/*` | 写需 token |
| Analytics | `/analytics/*` | 否（读接口） |
| Reports | `/reports/*`、`/reports/{id}/export/pdf` | 生成/删除需 token |

## 相关文档

| 文档 | 内容 |
|------|------|
| [USAGE.md](USAGE.md) | 用户使用说明：完整工作流、API 示例 |
| [docs/DATA_PREPARATION_GUIDE.md](docs/DATA_PREPARATION_GUIDE.md) | 数据准备与评测任务指南：原始数据 → 评测数据 → 任务前准备 |
| [TESTING_GUIDE.md](TESTING_GUIDE.md) | 测试指南 |
| [docs/docker-deployment.md](docs/docker-deployment.md) | 生产 Docker 部署 |
| [docs/postgres-migration-guide.md](docs/postgres-migration-guide.md) | SQLite → PostgreSQL 迁移指南 |
| [docs/production-readiness-evaluation.md](docs/production-readiness-evaluation.md) | 生产就绪评估 |
| [docs/FUTURE-DISTRIBUTED-QUEUE.md](docs/FUTURE-DISTRIBUTED-QUEUE.md) | 分布式任务队列设计 |
| [docs/tech/benchmarkops-distributed-queue.md](docs/tech/benchmarkops-distributed-queue.md) | 技术文章：分布式评测队列的工程演进 |
| [docs/tech/benchmarkops-reproducible-eval.md](docs/tech/benchmarkops-reproducible-eval.md) | 技术文章：可复现、脱敏与审计设计 |
| [sample-data/real-world/README.md](sample-data/real-world/README.md) | 真实评测数据集与一键复现 |
| [docs/real-world-eval/significance.md](docs/real-world-eval/significance.md) | A/B 统计显著性检验结果（bootstrap 置信区间 + 配对检验） |
| [SECURITY.md](SECURITY.md) | 安全策略与密钥事件记录 |

## 已知限制与注意事项

> **⚠️ 部署前必读**

<details>
<summary>🔒 数据安全</summary>

- `.env` 文件已被 `.gitignore` 排除，**请勿将包含 API Key 的 `.env` 提交到仓库**。
- **七牛云 API Key 曾泄露**：开发早期将 Key 作为示例写入 `references/openapi.json` 并提交；已吊销并替换为占位符，详见 [SECURITY.md](SECURITY.md)。
- `API_TOKEN` 是**全局共享密钥**，非用户/租户系统。生产环境务必设置。
- **生产环境强制鉴权**：`APP_ENV=production` 且未设置 `API_TOKEN` 时，应用拒绝启动。
- **SSE 进度流鉴权**：启用 `API_TOKEN` 后，`/experiments/{id}/stream` 会校验 `?token=` 参数（EventSource 无法设置请求头）。

</details>

<details>
<summary>🗄️ 数据库</summary>

- v1 默认使用 **SQLite**，仅支持**单进程写入**。应用启动时会为每个数据库文件创建独立的原子 writer lock，异常退出留下的过期锁会自动恢复。多实例部署必须切换为 PostgreSQL：
  ```env
  DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/benchmarkops
  ```
- 数据库文件 `benchmarkops.db` 会在首次启动时自动创建在 `backend/` 目录下。

</details>

<details>
<summary>⚙️ 评测运行</summary>

- 默认（`TASK_QUEUE_BACKEND=asyncio`）评测在**进程内执行**，进程重启会中断进行中的实验；启动恢复逻辑会把遗留的 running/queued 实验标记为 failed。
- 设置 `TASK_QUEUE_BACKEND=arq` 后，评测任务持久化在 **Redis（ARQ）** 中，由独立 worker（`uv run arq app.worker.WorkerSettings`）消费，支持多 worker / 多副本与重启不丢任务；此时启动恢复不会误标 queued/running 实验。
- **计费安全**：ARQ 仅对“调用 Provider 之前”的瞬态失败（如数据库锁）自动重试；429 / 配额耗尽 / 行级错误一律标记失败，人工重试。
- **Redis 必须开启 AOF 持久化**（compose 中已配置 `--appendonly yes`），否则 Redis 自身重启会丢失队列任务。
- **多写者约束**：compose 默认后端 + worker 共享 SQLite，存在 `database is locked` 风险；生产环境请按 [docs/postgres-migration-guide.md](docs/postgres-migration-guide.md) 切换 PostgreSQL，或保持单 backend + 任务侧 worker 的部署形态。
- 未配置 `DEEPSEEK_API_KEY` / `QINIU_API_KEY` / `OPENROUTER_API_KEY` 时，自动使用 **Mock Provider** 生成合成结果，可用于功能演示。

</details>

<details>
<summary>📤 数据集上传</summary>

- **支持格式**：JSONL（推荐）、JSON、CSV、TSV、XLSX；扩展名自动识别，也可手动指定 `format`。编码支持 UTF-8（含 BOM）、GBK/GB2312、UTF-16（带 BOM）。
- **大小限制**：单文件 ≤ 50 MB（`MAX_UPLOAD_BYTES`），行数 ≤ 100,000 行（`MAX_DATASET_ROWS`），**空文件直接拒绝**。
- **异步导入**：大文件推荐 `POST /datasets/import`（返回导入任务、行级进度，支持 `idempotency_key` 幂等）；同步 `POST /datasets/upload` 仍可用。
- **字段约定**：每行至少包含输入字段和期望输出字段。期望输出常见键名：`answer` / `expected` / `label` / `output` / `target` / `ground_truth`（大小写不敏感）。
- **JSONL 示例**：
  ```jsonl
  {"question": "Compute 2 + 2.", "answer": "4"}
  {"question": "Translate to French: hello", "answer": "bonjour"}
  ```
- **CSV/TSV** 必须包含表头行；**JSON** 根节点必须是数组，或包含 `data` / `rows` 键的数组。
- **内容校验**：`json/jsonl/xlsx` 校验文件魔数；`required_fields` / `field_types` 支持逐行校验，行级错误返回在 `error_rows`。
- **嵌套字段**：提示词模板变量支持路径寻址（`{user.address.city}`、`{items.0}`），dict/list 值以 JSON 序列化渲染。
- **多轮对话与 few-shot**：声明 `structured_chat=true` 后，`messages` 字段成为对话链、`examples` 字段渲染为 Q/A 示例；未开启时按普通输入列处理。
- **版本管理**：数据集不可原地修改，通过 `POST /datasets/{id}/versions` 创建替换/追加版本并激活回滚；实验创建时快照数据集版本，保证结果可复现。
- **敏感字段**：声明 `sensitive_fields` 后，预览接口与实验结果（`?mask_sensitive=true`）会脱敏显示。
- **审计**：创建、版本、激活、归档、删除、导入均记录审计事件（`GET /datasets/{id}/audit`）。
- **存储**：数据逐行存入数据库（保留 SHA-256 `content_hash`），非对象存储；大文件会影响数据库体积与备份时间。
- **字段角色冲突**：同一列不能同时映射到 input / expected / metadata 多个角色，否则上传失败。

</details>

<details>
<summary>🖥️ 前端 SSR</summary>

- Next.js 14 的 Server Components 无法序列化非普通对象（如 `Date`、自定义类实例）。
- `QueryClient` 必须在 Client Component 内部创建（见 [react-query-client.tsx](frontend/src/lib/react-query-client.tsx)）。
- 如遇 "Classes or null prototypes are not supported" 错误，确保没有在服务端组件中传递复杂对象给 Client Component。

</details>

<details>
<summary>ℹ️ 其他限制</summary>

- **无多租户 / 无组织隔离**：所有项目共享同一数据库与同一 token 空间。
- **报告导出**：支持 Markdown（`.md`）和 PDF（`.pdf`）下载；PDF 依赖 `weasyprint`，若运行环境缺少其系统依赖则接口返回 501。
- **鉴权**：当前为单 token 简化方案，非完整用户/租户系统。

</details>

## 路线图

| 阶段 | 计划 |
|------|------|
| **v2** | ARQ 分布式任务队列（✅ 已落地）、Redis 缓存、MinIO 对象存储 |
| **v3** | 多租户 / 组织隔离、完整 RBAC 权限系统 |
| **v4** | Multi-Agent 评测层、自定义评测智能体 |

## 贡献

欢迎提交 Issue 和 Pull Request！提交前请阅读 [USAGE.md](USAGE.md) 与 [TESTING_GUIDE.md](TESTING_GUIDE.md)，并确保本地测试通过。

## License

[MIT](LICENSE)

---

Built with ❤️ by the BenchmarkOps team.

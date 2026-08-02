# BenchmarkOps

<div align="center">

**Enterprise AI Evaluation & Benchmark Operations Platform**

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?logo=fastapi)](https://fastapi.tiangolo.com/) [![Next.js](https://img.shields.io/badge/Next.js-000?logo=next.js)](https://nextjs.org/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

BenchmarkOps 是一个企业级 **AI 评测 / 基准运维（Evaluation & Benchmark Operations）平台**，用于围绕统一的评测工作流管理数据集、基准、提示词、模型、实验、分析与报告。

```
Project → Dataset → Benchmark → Prompt → Model → Experiment → Run → Compare → Report
```

## ✨ 功能

| 模块 | 说明 |
|------|------|
| **项目管理** | 创建、归档项目，所有资源按项目隔离 |
| **模型中心** | 统一注册表，支持多 Provider（OpenRouter / Qiniu AI / Mock），含定价与能力标签 |
| **数据集** | 上传 JSONL / JSON / CSV 评测样例，支持预览与校验 |
| **基准（Benchmarks）** | 定义评测协议（qa / coding / agent / classification / generation），内置多种评分指标 |
| **提示词库** | 可复用模板，单花括号变量占位符（`{question}`），版本化管理 |
| **实验运行** | 绑定数据集 + 基准 + 提示词 + 模型，异步执行评测，实时进度轮询；创建时保存模型的 Provider 与免费模型状态快照 |
| **对比分析** | 柱状图对比多个实验的准确率、延迟、花费、令牌数 |
| **AI 报告** | 基于实验生成结构化 Markdown 报告，支持 AI 生成或确定性模板回退，并可导出 PDF |
| **仪表盘** | 总览项目、实验状态、准确率趋势、模型排行榜 |
| **行业雷达** | 汇总全部实验与模型的整体洞察：KPI、供应商准确率雷达图、状态环图 |

## 🏗 技术栈

| 层 | 技术 |
|----|------|
| **前端** | Next.js 14 (App Router) · React 18 · TypeScript · Tailwind CSS v4 · ECharts · lucide-react |
| **后端** | FastAPI · SQLAlchemy 2.0 (async) · Pydantic v2 · uvicorn |
| **数据库** | SQLite (aiosqlite, v1) → 可切换 PostgreSQL (postgresql+asyncpg) |
| **Provider** | Qiniu AI (默认) + OpenRouter + Mock fallback；实验快照固定实际 Provider 路由 |
| **Runner** | 进程内 asyncio 任务队列（默认）/ Redis + ARQ 分布式队列（可切换），支持并发限制、取消、任务持久化与崩溃恢复 |

**架构**：Clean Architecture，严格分层 `Router（薄层）→ Service（业务逻辑）→ Repository（数据访问）→ ORM`。Provider 注册表可插拔 — 新增 provider / 指标 / 模块只需新增文件，无需修改既有逻辑。

## 📸 截图

> （部署后在此处添加产品截图）

## 🚀 快速开始

### 环境要求

- **Python** ≥ 3.11
- **Node.js** ≥ 18（推荐 20+）
- **uv** — Python 包管理器 ([安装指南](https://docs.astral.sh/uv/getting-started/installation/))
- **npm** — Node 包管理器

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
- API 文档：**http://localhost:8000/docs**
- 健康检查：**http://localhost:8000/api/v1/health**

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

前端就绪后访问 **http://localhost:3000**。

#### 3. 灌入 Demo 数据（可选）

```bash
cd backend
uv run python -m app.seed
```

自动创建一套完整 Demo：项目、8 个模型、数据集、基准、提示词、2 个实验及报告。打开前端进入 **Demo: QA Benchmark** 项目即可查看。

### 方式二：Docker Compose 一键启动

```bash
docker compose up --build
```

后端 → http://localhost:8000  
前端 → http://localhost:3000

## ⚙️ 配置说明

### 后端 `.env` 关键配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `API_TOKEN` | *(空)* | 全局鉴权 token。留空 = 不强制鉴权（Demo/Mock 模式）；配置后所有写请求需 `Authorization: Bearer <token>` |
| `DATABASE_URL` | `sqlite+aiosqlite:///./benchmarkops.db` | 数据库连接串。生产环境建议切换为 PostgreSQL |
| `OPENROUTER_API_KEY` | *(空)* | OpenRouter API 密钥。**留空自动走 Mock Provider**，所有功能可离线使用 |
| `QINIU_API_KEY` | *(空)* | 七牛云 AI Token API 密钥 |
| `BACKEND_CORS_ORIGINS` | `http://localhost:3000,...` | 允许的浏览器来源，换端口/域名时必须同步更新 |
| `EVAL_MAX_WORKERS` | `4` | 单 worker 进程内的评测并发上限（进程内队列 / ARQ 均生效） |
| `TASK_QUEUE_BACKEND` | `asyncio` | 任务队列后端：`asyncio`（进程内，默认）或 `arq`（Redis 分布式队列） |
| `REDIS_DSN` | `redis://localhost:6379/0` | ARQ 队列与 worker 使用的 Redis 连接串（仅 `arq` 模式） |
| `TASK_MAX_TRIES` | `2` | 单任务最大尝试次数；仅瞬态、计费前失败会重试，Provider 侧失败不重试 |
| `TASK_RETRY_AFTER` | `30` | 瞬态失败后的重试等待秒数 |
| `MAX_UPLOAD_BYTES` | `52428800` (50 MB) | 数据集上传大小上限 |
| `MAX_DATASET_ROWS` | `100000` | 数据集行数上限 |

### 前端 `.env.local` 关键配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000/api/v1` | 前端调用的后端 API 基址 |

## 📁 项目结构

```
backend/
├── app/
│   ├── api/v1/routes/      # API 路由层
│   ├── core/               # 配置、数据库、异常处理
│   ├── evaluation/         # 评测引擎：runner、metrics、task queue
│   ├── providers/          # LLM Provider 注册表（可插拔）
│   ├── repositories/       # 数据访问层（Repository 抽象）
│   └── services/           # 业务逻辑层
frontend/
├── src/
│   ├── app/                # Next.js App Router 页面
│   ├── components/         # React 组件（UI / 图表 / 布局）
│   └── lib/                # API 客户端、工具函数
```

## 🧪 测试

```bash
cd backend
uv run pytest              # 运行单元测试
uv run pytest -m e2e       # 运行端到端测试（需网络）

cd ../frontend
npm run lint                # ESLint 检查
npm run build               # Next.js 生产构建
```

当前基线：后端 pytest 全量通过（`334 passed, 7 skipped`，由 GitHub Actions 自动执行）；前端 TypeScript、lint 和生产构建均已通过。

## 📡 API 概览

所有 API 端点在 `/api/v1` 下，完整文档在 `/docs`（Swagger UI）。

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

## 🔒 注意事项 & 已知限制

> **⚠️ 重要：部署前必读**

### 数据安全

- **`.env` 文件已被 `.gitignore` 排除**，请勿将包含 API Key 的 `.env` 提交到仓库。
- **七牛云 API Key 已泄露**（参见历史 commit）：如曾在此仓库提交过 `.env`，请**立即在七牛云控制台吊销并重发 API Key**。
- `API_TOKEN` 是**全局共享密钥**，非用户/租户系统。生产环境务必设置。
- **生产环境强制鉴权**：`APP_ENV=production` 且未设置 `API_TOKEN` 时，应用拒绝启动。
- **SSE 进度流鉴权**：启用 `API_TOKEN` 后，`/experiments/{id}/stream` 也会校验 `?token=` 参数（EventSource 无法设置请求头）。

### 数据库

- v1 默认使用 **SQLite**，仅支持**单进程写入**。应用启动时会为每个数据库文件创建独立的原子 writer lock，异常退出留下的过期锁会自动恢复。多实例部署必须切换为 PostgreSQL：
  ```env
  DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/benchmarkops
  ```
- 数据库文件 `benchmarkops.db` 会在首次启动时自动创建在 `backend/` 目录下。

### 评测运行

- 默认（`TASK_QUEUE_BACKEND=asyncio`）评测在**进程内执行**，进程重启会中断进行中的实验；启动恢复逻辑会把遗留的 running/queued 实验标记为 failed。
- 设置 `TASK_QUEUE_BACKEND=arq` 后，评测任务持久化在 **Redis（ARQ）** 中，由独立 worker（`uv run arq app.worker.WorkerSettings`）消费，支持多 worker / 多副本与重启不丢任务；此时启动恢复不会误标 queued/running 实验。
- **计费安全**：ARQ 仅对“调用 Provider 之前”的瞬态失败（如数据库锁）自动重试；429 / 配额耗尽 / 行级错误一律标记失败，人工重试。
- **Redis 必须开启 AOF 持久化**（compose 中已配置 `--appendonly yes`），否则 Redis 自身重启会丢失队列任务。
- **多写者约束**：compose 默认后端 + worker 共享 SQLite，存在 `database is locked` 风险；生产环境请按 [docs/postgres-migration-guide.md](docs/postgres-migration-guide.md) 切换 PostgreSQL，或保持单 backend + 任务侧 worker 的部署形态。
- 未配置 `OPENROUTER_API_KEY` 或 `QINIU_API_KEY` 时，自动使用 **Mock Provider** 生成合成结果，可用于功能演示。

### 数据集上传注意事项

- **支持格式**：JSONL（推荐）、JSON、CSV、TSV、XLSX。扩展名自动识别，也可手动指定 `format`。
- **大小限制**：单文件 ≤ 50 MB（`MAX_UPLOAD_BYTES`），行数 ≤ 100,000 行（`MAX_DATASET_ROWS`）。超出将在上传阶段被拒绝。
- **异步导入**：大文件推荐使用 `POST /datasets/import` 异步导入（返回导入任务，前端轮询进度，任务带行级 `progress` / `total_rows`）；`POST /datasets/upload` 同步接口仍可用。导入任务支持 `idempotency_key`，同一 key 重试不会产生重复数据集。
- **空文件拒绝**：0 行的数据集在上传、创建版本、异步导入时都会被服务端拒绝（422 / 导入任务失败）。
- **字段约定**：每行至少包含输入字段和期望输出字段。期望输出的常见键名：`answer` / `expected` / `label` / `output` / `target` / `ground_truth`，自动检测时大小写不敏感（`Answer` / `Expected` 等也会识别）。
- **JSONL 格式示例**：
  ```jsonl
  {"question": "Compute 2 + 2.", "answer": "4"}
  {"question": "Translate to French: hello", "answer": "bonjour"}
  ```
- **CSV/TSV 格式要求**：必须包含表头行，否则解析失败。
- **JSON 格式**：根节点必须是数组，或包含 `data` / `rows` 键的数组。
- **编码**：UTF-8（含 BOM）、GBK/GB2312、UTF-16（带 BOM）均支持；无法解码会给出明确错误。
- **内容校验**：`json/jsonl/xlsx` 会校验文件魔数（如 xlsx 必须是 zip 容器），误标格式会在上传阶段拒绝。
- **空行处理**：JSONL 中空行会被跳过；纯空白字符串视为空值（影响必填校验和空值统计）。
- **必填字段校验**：可通过 `required_fields` 配置哪些列不能为空；`field_types` 可声明字段类型（string / number / integer / boolean / array / object / json），导入时逐行校验，行级错误会返回（异步任务记录在 `error_rows`）。
- **嵌套字段**：提示词模板变量支持路径寻址，如 `{user.address.city}`、`{items.0}`；dict/list 值会以 JSON 序列化渲染。
- **版本管理**：数据集不可原地修改，可通过 `POST /datasets/{id}/versions` 创建替换/追加版本，`POST /datasets/{id}/versions/{v}/activate` 回滚激活；实验创建时快照数据集版本，保证结果可复现。
- **敏感字段**：上传时可声明 `sensitive_fields`（如 `["email"]`），预览接口会以 `[REDACTED]` 脱敏显示；实验详情的结果接口支持 `?mask_sensitive=true` 按数据集声明脱敏（前端有"脱敏显示"开关）。
- **审计**：数据集的创建、版本、激活、归档、删除、导入均记录审计事件，可通过 `GET /datasets/{id}/audit` 查询。
- **数据存储在数据库中**：上传内容解析后逐行存入 SQLite（保留 SHA-256 `content_hash`），非对象存储。大文件会影响数据库体积和备份时间。生产环境建议控制文件大小或使用后续迭代的 MinIO 方案。
- **字段角色冲突**：同一列不能同时映射到 input / expected / metadata 多个角色，否则上传失败。

### 前端 SSR

- Next.js 14 的 Server Components 无法序列化非普通对象（如 `Date`、自定义类实例）。
- `QueryClient` 必须在 Client Component 内部创建（见 [react-query-client.tsx](frontend/src/lib/react-query-client.tsx)）。
- 如遇 "Classes or null prototypes are not supported" 错误，确保没有在服务端组件中传递复杂对象给 Client Component。

### 其他限制

- **无多租户 / 无组织隔离**：所有项目共享同一数据库与同一 token 空间。
- **报告导出**：支持 Markdown（`.md`）和 PDF（`.pdf`）下载；PDF 依赖 `weasyprint`，若运行环境缺少其系统依赖则接口返回 501。
- **鉴权**：当前为单 token 简化方案，非完整用户/租户系统。

## 🛣 路线图

| 阶段 | 计划 |
|------|------|
| **v2** | ARQ 分布式任务队列（✅ 已落地）、Redis 缓存、MinIO 对象存储 |
| **v3** | 多租户 / 组织隔离、完整 RBAC 权限系统 |
| **v4** | Multi-Agent 评测层、自定义评测智能体 |

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 License

[MIT](LICENSE)

---

Built with ❤️ by the BenchmarkOps team.

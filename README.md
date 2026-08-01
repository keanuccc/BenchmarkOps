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
| **Runner** | 进程内 asyncio 任务队列，支持并发限制、取消与崩溃恢复 |

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
| `EVAL_MAX_WORKERS` | `4` | 评测并发 worker 数（进程内 asyncio 任务队列） |
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

当前基线：后端 `233 passed, 11 deselected`；前端 TypeScript、lint 和生产构建均已通过。

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

### 数据库

- v1 默认使用 **SQLite**，仅支持**单进程写入**。应用启动时会为每个数据库文件创建独立的原子 writer lock，异常退出留下的过期锁会自动恢复。多实例部署必须切换为 PostgreSQL：
  ```env
  DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/benchmarkops
  ```
- 数据库文件 `benchmarkops.db` 会在首次启动时自动创建在 `backend/` 目录下。

### 评测运行

- 当前评测在**进程内执行**，进程重启会中断进行中的实验。
- `EVAL_MAX_WORKERS` 在 v1 中为预留配置项，实际并发由进程内线程队列控制。
- 未配置 `OPENROUTER_API_KEY` 或 `QINIU_API_KEY` 时，自动使用 **Mock Provider** 生成合成结果，可用于功能演示。

### 数据集上传注意事项

- **支持格式**：JSONL（推荐）、JSON、CSV。扩展名自动识别，也可手动指定 `format`。
- **大小限制**：单文件 ≤ 50 MB（`MAX_UPLOAD_BYTES`），行数 ≤ 100,000 行（`MAX_DATASET_ROWS`）。超出将在上传阶段被拒绝。
- **字段约定**：每行至少包含输入字段和期望输出字段。期望输出的常见键名：`answer` / `expected` / `label` / `output` / `target` / `ground_truth`。系统会自动检测这些键。
- **JSONL 格式示例**：
  ```jsonl
  {"question": "Compute 2 + 2.", "answer": "4"}
  {"question": "Translate to French: hello", "answer": "bonjour"}
  ```
- **CSV 格式要求**：必须包含表头行，否则解析失败。
- **JSON 格式**：根节点必须是数组，或包含 `data` / `rows` 键的数组。
- **编码**：优先 UTF-8；Windows 导出的 CSV 如为 GBK/GB2312 编码会自动回退解码。
- **空行处理**：JSONL 中空行会被跳过；CSV 中空行会报错。
- **必填字段校验**：可通过 `required_fields` 配置哪些列不能为空。校验接口 `POST /datasets/{id}/validate` 可检查数据完整性。
- **数据存储在数据库中**：上传内容以原始字节存入 SQLite，非对象存储。大文件会影响数据库体积和备份时间。生产环境建议控制文件大小或使用后续迭代的 MinIO 方案。
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
| **v2** | Redis 缓存、Celery 分布式任务队列、MinIO 对象存储 |
| **v3** | 多租户 / 组织隔离、完整 RBAC 权限系统 |
| **v4** | Multi-Agent 评测层、自定义评测智能体 |

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 License

[MIT](LICENSE)

---

Built with ❤️ by the BenchmarkOps team.

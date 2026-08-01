# BenchmarkOps 生产化上线方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从"能跑的 Demo"升级为"可交付的生产级 AI 评测平台"，明确优先级、缺口和路线图。

**Architecture:** 基于现有 Clean Architecture + FastAPI + Next.js 栈，在 v1 基础上补齐生产化关键能力：健壮性、安全性、可观测性、数据工程、用户体验。

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy 2.0 async / SQLite → PostgreSQL / Next.js 14 / React 18 / Tailwind CSS v4 / uv / npm

---

## 项目现状总结

BenchmarkOps 是一个企业级 AI 评测/基准运维平台，核心工作流：

```
Project → Dataset → Benchmark → Prompt → Model → Experiment → Run → Compare → Report
```

**已完成（v1）：**
- ✅ Clean Architecture 分层（Router → Service → Repository → ORM）
- ✅ 多 Provider 路由（OpenRouter + Qiniu + Mock）
- ✅ 评测引擎（答案抽取、6 种指标、F1/LLM Judge）
- ✅ 后台任务队列 + 实验状态恢复
- ✅ SQLite 并发治理（WAL + busy_timeout + CAS + lock retry）
- ✅ 429 智能退避 + 熔断器
- ✅ SSE 实时进度 + /ready 就绪探针
- ✅ Toast 通知 + 网络断开 Banner
- ✅ 可折叠侧边栏 + 键盘快捷键
- ✅ 实验结果分页 + sticky header
- ✅ JWT 认证 + Settings UI + API Token 管理
- ✅ 数据集契约解析 + 实验快照
- ✅ /metrics 端点 + structured logging
- ✅ GitHub Actions E2E CI
- ✅ 完整文档（README / USAGE / TESTING_GUIDE / LOOP_PLAN / OPTIMIZATION_PLAN / production-readiness-evaluation）
- ✅ 29 个后端测试文件（约 40+ 用例通过）

**当前定位：** 功能完整的 Demo / v1 平台，可离线跑通全链路，适合演示和个人使用。

**生产化缺口：** 以下分析基于对代码库、文档、LOOP_PLAN、OPTIMIZATION_PLAN、production-readiness-evaluation 的全面审查。

---

## 优先级分级

### P0 — 上线前必须修复（不做无法交付）

| # | 问题 | 严重度 | 影响 |
|---|------|--------|------|
| P0-1 | **SQLite 单写者约束无保障** | 高 | 两个 backend 进程共享同一 SQLite 会静默丢失状态；当前仅靠文档约束，无运行时检查 |
| P0-2 | **前端无请求缓存/去重** | 高 | Dashboard 一次性 4 个并行请求无缓存，频繁刷新页面导致重复 API 调用；实验结果列表无虚拟化和服务端分页 |
| P0-3 | **`.env.example` 不完整** | 中 | `backend/.env.example` 缺少 `API_TOKEN`、`MAX_UPLOAD_BYTES`、`MAX_DATASET_ROWS`、`QINIU_API_KEY` 等关键配置项，新用户按文档搭建会踩坑 |
| P0-4 | **README 与实现多处不一致** | 中 | README 说 "Next.js 16" 但实际已降级到 14；说 "Celery (later)" 但已有后台任务队列；说 "OpenRouter single gateway" 但已有七牛云双网关 |

### P1 — 强烈建议补齐（做了才能放心交付）

| # | 问题 | 严重度 | 影响 |
|---|------|--------|------|
| P1-1 | **数据集上传无预览/校验反馈** | 高 | 用户上传后不知道格式是否正确，直到创建实验时才报错 |
| P1-2 | **报告只有 Markdown** | 中 | 企业场景需要 PDF/HTML 导出 |
| P1-3 | **无多租户/组织隔离** | 高 | 所有项目共享同一数据库和 token 空间，无法用于多团队场景 |
| P1-4 | **答案抽取正则 ~70 行无充分测试覆盖** | 高 | 最近一次实验准确率 0.0033 的根因就是抽取逻辑未处理中文前缀 |
| P1-5 | **无数据库备份/恢复机制** | 中 | SQLite 单文件虽简单，但无定期备份策略，数据丢失风险高 |
| P1-6 | **前端无 TypeScript strict mode** | 中 | `package.json` 未启用 `strict: true`，存在 `any` 类型泄漏（如 page.tsx 中的 `(e as any)`） |

### P2 — 锦上添花（有时间再做）

| # | 问题 | 严重度 | 影响 |
|---|------|--------|------|
| P2-1 | **无 WebSocket 推送** | 低 | 当前用 SSE 替代了轮询，但 SSE 有浏览器连接数限制 |
| P2-2 | **无 A/B Test 专用视图** | 低 | 只能手动筛选对比，没有一键 A/B 测试工作流 |
| P2-3 | **无定时任务/CI/CD 集成** | 中 | 模型更新后无法自动跑回归测试 |
| P2-4 | **无对象存储（MinIO）** | 低 | 数据集存数据库，大文件受 50MB 限制 |
| P2-5 | **无 Docker 部署** | 中 | 部署依赖手动操作，无一键 Docker Compose |

---

## 详细实施计划

### Phase 1: 修复已知问题（预计 2-3 天）

#### 任务 1.1: 补齐 `.env.example`

**文件:**
- Modify: `backend/.env.example`

- [ ] **Step 1: 对照 `config.py` 补齐所有环境变量**

  将以下缺失项加入 `.env.example`：
  ```
  # Auth
  API_TOKEN=

  # Dataset limits
  MAX_UPLOAD_BYTES=52428800
  MAX_DATASET_ROWS=100000

  # Qiniu provider
  QINIU_API_KEY=
  QINIU_BASE_URL=https://api.qnaigc.com/v1
  QINIU_RPM_CAP=75
  QINIU_RPD_CAP=5000
  QINIU_FREE_MODELS=

  # Evaluation
  EVAL_MAX_WORKERS=4
  EVAL_REQUEST_TIMEOUT=60
  FREE_MODEL_CONCURRENCY=5
  FREE_MODEL_RPM_CAP=300
  ```

- [ ] **Step 2: 同步更新 `frontend/.env.local.example`**
  确认包含 `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1`

- [ ] **Step 3: 验证**
  ```bash
  cd backend && cp .env.example .env && grep -c "API_TOKEN\|MAX_UPLOAD\|QINIU_API" .env
  # 预期: 至少匹配 6 次
  ```

#### 任务 1.2: 修正 README 与实际不符之处

**文件:**
- Modify: `README.md`

- [ ] **Step 1: 更新技术栈描述**
  - "Next.js 16" → "Next.js 14 (App Router)"
  - "OpenRouter single gateway" → "Multi-provider: OpenRouter + Qiniu AI + Mock"
  - "Runner: In-process threaded task queue → Celery" → "Runner: Background task queue with cancellation + recovery (Celery planned)"
  - "Reserved: Redis, Celery, MinIO, multi-Agent layer" → "Planned: Redis caching, Celery distributed queue, MinIO object storage"

- [ ] **Step 2: 添加部署注意事项**
  在 Run 章节增加：
  > **生产约束：** 只启动一个 backend 进程写 SQLite。若需多实例，请切换 `DATABASE_URL` 到 PostgreSQL。

- [ ] **Step 3: 验证**
  `cat README.md | grep -i "next.js\|gateway\|celery"` 确认更新后内容准确

#### 任务 1.3: SQLite 单写者运行时保护

**文件:**
- Modify: `backend/app/core/database.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: 在 `database.py` 中添加单写者检测**

  在 `init_db()` 或 `get_async_session()` 中，启动时写入一个带 PID 的文件锁（如 `/tmp/benchmarkops_writer.pid`），如果已存在且 PID 不同则 warn 并拒绝启动。

  ```python
  import pathlib, os, signal

  WRITER_LOCK = pathlib.Path("/tmp/benchmarkops_writer.lock")

  def acquire_writer_lock():
      if WRITER_LOCK.exists():
          old_pid = int(WRITER_LOCK.read_text().strip())
          if old_pid != os.getpid():
              try:
                  os.kill(old_pid, 0)  # check if process alive
              except OSError:
                  WRITER_LOCK.unlink()  # stale lock, remove
              else:
                  raise RuntimeError(
                      f"Another BenchmarkOps instance is already writing to the database (PID {old_pid}). "
                      "SQLite supports only one writer. Stop the other instance or switch to PostgreSQL."
                  )
      WRITER_LOCK.write_text(str(os.getpid()))
  ```

- [ ] **Step 2: 在 `main.py` lifespan 中调用**

  ```python
  from app.core.database import init_db, acquire_writer_lock

  async def lifespan(app):
      acquire_writer_lock()  # ← 新增
      await init_db()
      await _recover_stale_experiments()
      yield
  ```

- [ ] **Step 3: 添加测试**

  **文件:** Create: `backend/tests/test_single_writer.py`

  - [ ] 测试 1: 正常启动时锁文件不存在 → 创建成功
  - [ ] 测试 2: 锁文件存在且 PID 相同 → 不抛异常
  - [ ] 测试 3: 锁文件存在且 PID 不同（进程存活）→ 抛 RuntimeError
  - [ ] 测试 4: 锁文件存在且 PID 不同（进程死亡）→ 删除旧锁，创建新锁

- [ ] **Step 4: 运行测试**
  ```bash
  cd backend && uv run pytest tests/test_single_writer.py -v
  ```

### Phase 2: 增强用户体验（预计 3-4 天）

#### 任务 2.1: 数据集上传预览与即时校验

**文件:**
- Modify: `backend/app/api/v1/routes/datasets.py`
- Modify: `backend/app/services/dataset_parser.py`
- Modify: `frontend/src/app/projects/[id]/page.tsx` (数据集 Tab)

- [ ] **Step 1: 后端新增 `POST /datasets/{id}/preview` 端点**

  返回前 10 行数据 + schema 统计（字段名、类型、空值率）。

- [ ] **Step 2: 后端新增 `POST /datasets/{id}/validate` 端点**

  校验契约：必填字段是否存在、prompt 变量是否匹配、expected 是否有效。返回 `{"valid": bool, "errors": [...]}`。

- [ ] **Step 3: 前端上传组件增加预览面板**

  文件选择后立即调用 `/preview`，显示前 5 行表格。点击"校验"按钮调用 `/validate`，展示校验结果。

#### 任务 2.2: 报告导出 PDF

**文件:**
- Modify: `backend/pyproject.toml` (添加 `weasyprint` 或 `markdown-pdf`)
- Modify: `backend/app/services/report_service.py`
- Modify: `backend/app/api/v1/routes/reports.py`

- [ ] **Step 1: 后端添加 PDF 导出端点**

  ```python
  @router.get("/{report_id}/export/pdf")
  async def export_report_pdf(report_id: str):
      report = await report_service.get(report_id)
      html = markdown_to_html(report.content)
      pdf_bytes = weasyprint.HTML(string=html).write_pdf()
      return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={report.title}.pdf"}
      )
  ```

- [ ] **Step 2: 前端报告页添加 "Export PDF" 按钮**

  与现有 ".md" 导出并列。

- [ ] **Step 3: 验证**
  手动创建报告 → 点击导出 PDF → 打开检查格式

#### 任务 2.3: 答案抽取测试覆盖率提升

**文件:**
- Create: `backend/tests/test_answer_extraction_edge_cases.py`

- [ ] **Step 1: 补充 edge case 测试（至少 30 条）**

  覆盖以下场景：
  - 中文前缀：`答案：4`、`答案是：4`、`最终答案：4`
  - 英文前缀：`Answer: 4`、`The answer is 4`、`Final Answer: 4`
  - CoT 多行：推理过程 + 最后一行答案
  - 嵌套括号：`答案：(A)`、`答案：{4}`
  - 单位：`答案：42 kg`、`答案：3.14 rad`
  - 标点噪音：`答案：亚洲。`、`答案：亚洲，`、`答案： 亚洲 `
  - 多行输出：模型输出换行后的最后一行
  - 空输出 / 纯推理无答案
  - CJK 字符边界
  - Unicode 全角/半角混用

- [ ] **Step 2: 运行**
  ```bash
  cd backend && uv run pytest tests/test_answer_extraction_edge_cases.py -v
  ```

#### 任务 2.4: 数据库备份端点完善

**文件:**
- Modify: `backend/app/api/v1/routes/db.py`
- Modify: `frontend/src/app/settings/page.tsx`

- [ ] **Step 1: 确认备份端点可用**

  已有 `POST /db/backup` 端点（在 `routes/db.py` 中），验证其返回正确的 `.db` 文件下载。

- [ ] **Step 2: 添加定时备份配置**

  新增环境变量 `BACKUP_SCHEDULE_CRON`（可选），如果设置则在 startup 注册 APScheduler 定时备份。

- [ ] **Step 3: 前端 Settings 页面添加备份 UI**

  "立即备份"按钮 + 历史备份列表（文件名 + 时间）。

### Phase 3: 生产化加固（预计 3-5 天）

#### 任务 3.1: 前端请求缓存（React Query / SWR）

**文件:**
- Modify: `frontend/package.json` (添加 `@tanstack/react-query`)
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/app/page.tsx` 及其他页面

- [ ] **Step 1: 安装 React Query**
  ```bash
  cd frontend && npm install @tanstack/react-query
  ```

- [ ] **Step 2: 在 root layout 包裹 QueryClientProvider**

  **文件:** `frontend/src/app/layout.tsx`

- [ ] **Step 3: 替换 `useEffect` + `useState` 为 `useQuery`**

  以 Dashboard 为例：
  ```tsx
  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: listProjects,
  });
  ```

- [ ] **Step 4: 验证**
  快速切换页面 → 观察网络面板，相同请求不应重复发送

#### 任务 3.2: Docker 一键部署

**文件:**
- Create: `docker-compose.yml`
- Create: `Dockerfile.backend`
- Create: `Dockerfile.frontend`
- Create: `.dockerignore`

- [ ] **Step 1: 编写 Backend Dockerfile**

  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  RUN pip install uv
  COPY pyproject.toml uv.lock ./
  RUN uv sync --frozen --no-dev
  COPY . .
  CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
  ```

- [ ] **Step 2: 编写 Frontend Dockerfile**

  ```dockerfile
  FROM node:20-alpine AS builder
  WORKDIR /app
  COPY package.json package-lock.json ./
  RUN npm ci
  COPY . .
  ARG NEXT_PUBLIC_API_BASE_URL
  RUN npm run build

  FROM node:20-alpine
  WORKDIR /app
  COPY --from=builder /app/.next ./ .next
  COPY --from=builder /app/node_modules ./node_modules
  COPY --from=builder /app/package.json ./
  ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
  CMD ["npm", "start"]
  ```

- [ ] **Step 3: 编写 docker-compose.yml**

  ```yaml
  version: "3.8"
  services:
    backend:
      build:
        context: .
        dockerfile: Dockerfile.backend
      ports: ["8000:8000"]
      env_file: backend/.env
      volumes: ["db_data:/app"]

    frontend:
      build:
        context: frontend
        dockerfile: ../Dockerfile.frontend
        args:
          NEXT_PUBLIC_API_BASE_URL: http://localhost:8000/api/v1
      ports: ["3000:3000"]
      depends_on: [backend]

  volumes:
    db_data:
  ```

- [ ] **Step 4: 验证**
  ```bash
  docker compose up --build -d
  curl localhost:3000
  curl localhost:8000/api/v1/health
  ```

#### 任务 3.3: PostgreSQL 切换指南

**文件:**
- Create: `docs/postgres-migration-guide.md`
- Modify: `backend/.env.example`

- [ ] **Step 1: 更新 `.env.example`**

  添加 PostgreSQL 示例：
  ```
  # For production, uncomment and adjust:
  # DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/benchmarkops
  ```

- [ ] **Step 2: 编写迁移指南**

  内容包括：
  1. 安装 PostgreSQL
  2. 创建数据库和用户
  3. 修改 `.env`
  4. 迁移 SQLite 数据到 Postgres（SQLAlchemy 导出/导入脚本）
  5. 验证

### Phase 4: 长期演进（按需）

| 任务 | 说明 | 预估 |
|------|------|------|
| P4-1: 多租户/组织系统 | 用户表 + 角色 + 项目归属隔离 | 1-2 周 |
| P4-2: Celery 分布式队列 | 替代进程内队列，支持横向扩展 | 3-5 天 |
| P4-3: MinIO 对象存储 | 数据集不再存数据库，支持大文件 | 2-3 天 |
| P4-4: A/B Test 工作流 | 一键对比同模型不同 prompt | 2-3 天 |
| P4-5: 定时回归测试 | APScheduler 定时触发实验 | 1-2 天 |
| P4-6: Webhook 通知 | 实验完成/失败时发送通知 | 1 天 |
| P4-7: 前端单元测试 | Testing Library + Vitest | 持续 |
| P4-8: 国际化 i18n | 中英文切换 | 3-5 天 |

---

## 交付物清单

上线前必须有的东西：

| # | 交付物 | 状态 | 备注 |
|---|--------|------|------|
| 1 | README.md 准确反映技术栈 | ✅ | Phase 1 — 修正 Next.js 版本、Provider 描述、Runner 描述 + 生产约束 |
| 2 | `.env.example` 完整无遗漏 | ✅ | Phase 1 — 新增 API_TOKEN、QINIU_*、FREE_MODEL_*、MAX_UPLOAD_BYTES、MAX_DATASET_ROWS |
| 3 | 答案抽取 edge case 测试 ≥30 条 | ✅ | Phase 2 — 81 条测试，77/81 pass（4 条为预期失败） |
| 4 | 数据集上传预览 + 校验 | ✅ | Phase 2 — 后端 preview/raw + validate/quick 端点 + 前端预览面板 |
| 5 | Docker Compose 一键部署 | ✅ | Phase 3 — Dockerfile.backend + frontend + docker-compose.yml + .dockerignore + 部署文档 |
| 6 | PostgreSQL 切换指南 | ✅ | Phase 3 — docs/postgres-migration-guide.md + scripts/migrate_to_postgres.py |
| 7 | 报告 PDF 导出 | ✅ | Phase 2 — weasyprint + markdown 依赖 + /reports/{id}/export/pdf 端点 + 前端按钮 |
| 8 | 前端请求缓存（React Query） | ✅ | Phase 3 — QueryClientProvider + Dashboard/Projects/Experiments/Compare 四页面迁移 |
| 9 | 数据库备份 UI | ⚠️ 部分 | 后端已有 POST /db/backup 端点，前端 Settings 备份 UI 待补 |
| 10 | SQLite 单写者保护 | ✅ | Phase 1 — acquire_writer_lock() + main.py 集成 + 5/5 测试通过 |
| 11 | CHANGELOG.md | ❌ | 建议新建 |
| 12 | 生产环境部署 checklist | ❌ | 建议新建 |

---

## 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| SQLite 在多进程下数据损坏 | 中 | 高 | Phase 1 单写者锁 + 文档约束 |
| 真实 API key 下 429 导致实验卡死 | 低 | 高 | 已有熔断器，Phase 1 验证 |
| 数据集上传大文件 OOM | 低 | 中 | 已有 50MB 限制，Phase 2 考虑分块 |
| Next.js 14 降级后的兼容性问题 | 低 | 中 | 已有 E2E CI 守护 |
| 中文前缀抽取仍有 edge case | 中 | 高 | Phase 2 补充 30+ 测试 |

---

## 推荐执行顺序

```
Phase 1 (2-3天) → Phase 2 (3-4天) → Phase 3 (3-5天) → Phase 4 (按需)
   ↑ 基础修复        ↑ 体验增强         ↑ 生产加固       ↑ 长期演进
```

**最小可行上线（MVP Production）：** 只做 Phase 1 + Phase 2 的任务 2.3（答案抽取测试）即可交付。其余可在后续迭代中逐步补齐。

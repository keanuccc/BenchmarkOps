# BenchmarkOps

<div align="right">

**English** | [简体中文](README.md)

</div>

<div align="center">

**Enterprise AI Evaluation & Benchmark Operations Platform**

[![Backend Tests](https://github.com/keanuccc/BenchmarkOps/actions/workflows/backend-tests.yml/badge.svg)](https://github.com/keanuccc/BenchmarkOps/actions/workflows/backend-tests.yml)
[![Frontend E2E](https://github.com/keanuccc/BenchmarkOps/actions/workflows/e2e.yml/badge.svg)](https://github.com/keanuccc/BenchmarkOps/actions/workflows/e2e.yml)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

BenchmarkOps is an enterprise-grade platform for managing datasets, benchmarks, prompts, models, experiments, analytics, and reports around a **unified evaluation workflow**:

```mermaid
flowchart LR
    A[Project] --> B[Dataset]
    B --> C[Benchmark]
    C --> D[Prompt]
    D --> E[Model]
    E --> F[Experiment]
    F --> G[Run]
    G --> H[Compare]
    H --> I[Report]
```

In short, it turns "running a model evaluation" from scattered scripts and hard-to-compare results into a **reproducible, auditable, comparable** pipeline.

### Highlights

- **Works out of the box**: falls back to a deterministic Mock provider when no API key is configured, so every feature can be demoed offline
- **Reproducible results**: experiments snapshot the model provider, dataset version, and prompt version when created
- **Pluggable architecture**: add a new provider, metric, or module by simply adding files — no changes to existing logic
- **Two queue backends**: in-process asyncio queue (default) and Redis + ARQ distributed queue (optional)
- **CI coverage**: backend unit tests and frontend Playwright E2E run on GitHub Actions

## Demo

<video src="videos/benchmarkops-demo/my-video/renders/benchmarkops-demo-v2.mp4" controls width="100%"></video>

![Dashboard](videos/benchmarkops-demo/my-video/capture/screenshots/full-page.png)

## Real-World Evaluation Results

The repo ships **real public datasets + real model evaluations** across two
gateways (Qiniu Cloud AI and OpenRouter), covering C-Eval (Chinese exam QA),
THUCNews (news classification) and HumanEval (Python code generation).
See [docs/real-world-eval/](docs/real-world-eval/) for the report and
[sample-data/real-world/README.md](sample-data/real-world/README.md) for the
one-command reproduction.

## Table of Contents

- [Features](#features)
- [Demo](#demo)
- [Real-World Evaluation Results](#real-world-evaluation-results)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Testing & CI](#testing--ci)
- [API Overview](#api-overview)
- [Documentation](#documentation)
- [Known Limitations and Notes](#known-limitations-and-notes)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

## Features

| Module | Description |
|--------|-------------|
| **Projects** | Create and archive projects; all resources are isolated per project |
| **Model Hub** | Unified model registry with multiple providers (OpenRouter / Qiniu AI / Mock), including pricing and capability tags |
| **Datasets** | Upload JSONL / JSON / CSV / TSV / XLSX evaluation samples with preview, validation, versioning, async import, sensitive-field redaction, and audit |
| **Benchmarks** | Define evaluation protocols (qa / coding / agent / classification / generation) with built-in scoring metrics |
| **Prompt Library** | Reusable templates with `{variable}` placeholders (including nested path addressing), versioned |
| **Experiment Runs** | Bind a dataset + benchmark + prompt + model, run evaluations asynchronously with real-time progress polling; snapshots the model provider and free-model state at creation |
| **Comparison** | Bar charts comparing accuracy, latency, cost, and token usage across experiments |
| **AI Reports** | Structured Markdown reports from experiment results (AI-generated or deterministic template fallback), exportable to PDF |
| **Dashboard** | Project overview, experiment status, accuracy trends, and model leaderboard |
| **Industry Radar** | Global insights across all experiments and models: KPIs, provider-accuracy radar chart, status donut chart |

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | Next.js 14 (App Router) · React 18 · TypeScript · Tailwind CSS v4 · ECharts · lucide-react |
| **Backend** | FastAPI · SQLAlchemy 2.0 (async) · Pydantic v2 · uvicorn |
| **Database** | SQLite (aiosqlite, default) → PostgreSQL (postgresql+asyncpg) |
| **LLM Providers** | Qiniu AI (default) · OpenRouter · Mock (offline fallback); experiments pin the actual provider route |
| **Task Queue** | In-process asyncio (default) · Redis + ARQ distributed queue (optional), with concurrency limits, cancellation, job persistence, and crash recovery |
| **Testing / CI** | pytest · Playwright · GitHub Actions |

## Architecture

The backend follows **Clean Architecture** with strict layering: `Router (thin) → Service (business logic) → Repository (data access) → ORM`. The provider registry is pluggable — adding a provider / metric / module only requires adding new files.

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
        REDIS[("Redis (ARQ optional)")]
    end
    subgraph LLM["LLM Providers"]
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
    EVAL --> P1 & P2 & P3
```

## Quick Start

### Prerequisites

- **Python** ≥ 3.11
- **Node.js** ≥ 18 (20+ recommended)
- **uv** — Python package manager ([install guide](https://docs.astral.sh/uv/getting-started/installation/))
- **npm** — Node package manager
- (Optional) **Docker**

### Option 1: Local Development

#### 1. Start the backend

```bash
cd backend

# Copy configuration
cp .env.example .env

# Create a virtual environment and install dependencies
uv venv --python 3.11
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"

# Start the server
uv run uvicorn app.main:app --reload --port 8000
```

Once the backend is up:

- API docs (Swagger UI): http://localhost:8000/docs
- Health check: http://localhost:8000/api/v1/health

#### 2. Start the frontend

```bash
cd frontend

# Copy configuration
cp .env.local.example .env.local

# Install dependencies
npm install

# Start the dev server
npm run dev
```

Open http://localhost:3000.

#### 3. Seed demo data (optional)

```bash
cd backend
uv run python -m app.seed
```

This creates a complete demo: one project, 8 models, a dataset, a benchmark, prompts, 2 experiments, and reports. Open the **Demo: QA Benchmark** project in the UI.

> 💡 Without `OPENROUTER_API_KEY` / `QINIU_API_KEY`, evaluation automatically uses the **Mock provider** — no network or API key required.

### Option 2: Docker Compose

```bash
docker compose up --build
```

The Compose stack includes Redis and an ARQ worker:

- Frontend: http://localhost:3000
- Backend: http://localhost:8000

### Production Deployment

For production (PostgreSQL + Redis/ARQ + dedicated worker), see [docs/docker-deployment.md](docs/docker-deployment.md).

## Configuration

### Backend `.env` (template: `backend/.env.example`)

| Variable | Default | Description |
|----------|---------|-------------|
| `API_TOKEN` | *(empty)* | Global auth token. Empty = no auth (Demo/Mock mode); when set, all write requests require `Authorization: Bearer <token>` |
| `APP_ENV` | `development` | When `production`, the app refuses to start without `API_TOKEN` |
| `DATABASE_URL` | `sqlite+aiosqlite:///./benchmarkops.db` | Database connection string; PostgreSQL recommended for production |
| `DEFAULT_PROVIDER` | `qiniu` | Default provider routing: `openrouter` / `qiniu` / `mock` |
| `OPENROUTER_API_KEY` | *(empty)* | OpenRouter API key; empty = automatic Mock provider fallback (works offline) |
| `QINIU_API_KEY` | *(empty)* | Qiniu Cloud AI Token API key |
| `BACKEND_CORS_ORIGINS` | `http://localhost:3000,...` | Allowed browser origins; must be updated when changing ports/domains |
| `TASK_QUEUE_BACKEND` | `asyncio` | Queue backend: `asyncio` (in-process, default) or `arq` (Redis distributed queue) |
| `REDIS_DSN` | `redis://localhost:6379/0` | Redis connection string for ARQ queue and workers (ARQ mode only) |
| `EVAL_MAX_WORKERS` | `4` | Max concurrent evaluations per worker process |
| `TASK_MAX_TRIES` | `2` | Max attempts per job; only transient pre-billing failures are retried, provider-side failures are not |
| `REPORT_MODEL_ID` | *(empty)* | Model used for AI report generation; empty = built-in default (`openai/gpt-4o-mini`) |
| `MAX_UPLOAD_BYTES` | `52428800` (50 MB) | Max dataset upload size |
| `MAX_DATASET_ROWS` | `100000` | Max dataset rows |

### Frontend `.env.local` (template: `frontend/.env.local.example`)

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000/api/v1` | Backend API base URL used by the frontend |

## Project Structure

```text
backend/
├── app/
│   ├── api/v1/routes/      # API route layer
│   ├── core/               # Config, database, security, exception handling
│   ├── evaluation/         # Evaluation engine: runner, metrics, task queue
│   ├── providers/          # LLM provider registry (pluggable)
│   ├── repositories/       # Data access layer (Repository abstractions)
│   ├── services/           # Business logic layer
│   ├── models/             # ORM models
│   ├── schemas/            # Pydantic schemas
│   ├── report/             # Report generation (AI / template / PDF)
│   └── migrations/         # Database migrations
frontend/
├── src/
│   ├── app/                # Next.js App Router pages
│   ├── components/         # React components (UI / charts / layout)
│   └── lib/                # API client, utilities
```

## Testing & CI

```bash
cd backend
uv run pytest              # Unit tests (e2e excluded by default)
uv run pytest -m e2e       # End-to-end tests (requires network)

cd ../frontend
npm run lint               # ESLint
npm run build              # Next.js production build
```

Current baseline: all backend pytest tests pass (`334 passed, 7 skipped`); frontend TypeScript, lint, and production build pass.

Two GitHub Actions workflows are included:

- **Backend Tests**: runs backend unit tests on push / PR
- **Frontend E2E**: starts the backend and frontend, then runs Playwright end-to-end tests

## API Overview

All endpoints are under `/api/v1`; interactive docs are available at `/docs` (Swagger UI).

| Group | Path | Auth |
|-------|------|------|
| Health | `GET /health` | No |
| Projects | `/projects/*` | Token for writes |
| Models | `/models/*` | Token for writes |
| Datasets | `/datasets/*` | Token for writes |
| Benchmarks | `/benchmarks/*` | Token for writes |
| Prompts | `/prompts/*` | Token for writes |
| Experiments | `/experiments/*` | Token for writes |
| Analytics | `/analytics/*` | No (read-only) |
| Reports | `/reports/*`, `/reports/{id}/export/pdf` | Token for generation/deletion |

## Documentation

| Document | Contents |
|----------|----------|
| [USAGE.md](USAGE.md) | User guide: full workflow and API examples |
| [TESTING_GUIDE.md](TESTING_GUIDE.md) | Testing guide |
| [docs/docker-deployment.md](docs/docker-deployment.md) | Production Docker deployment |
| [docs/postgres-migration-guide.md](docs/postgres-migration-guide.md) | SQLite → PostgreSQL migration guide |
| [docs/production-readiness-evaluation.md](docs/production-readiness-evaluation.md) | Production readiness evaluation |
| [docs/FUTURE-DISTRIBUTED-QUEUE.md](docs/FUTURE-DISTRIBUTED-QUEUE.md) | Distributed task queue design |
| [docs/tech/benchmarkops-distributed-queue.md](docs/tech/benchmarkops-distributed-queue.md) | Engineering deep-dive: distributed eval queue |
| [docs/tech/benchmarkops-reproducible-eval.md](docs/tech/benchmarkops-reproducible-eval.md) | Engineering deep-dive: reproducibility, redaction & audit |
| [sample-data/real-world/README.md](sample-data/real-world/README.md) | Real-world datasets & one-command reproduction |
| [SECURITY.md](SECURITY.md) | Security policy & key incident record |

## Known Limitations and Notes

> **⚠️ Read before deploying**

<details>
<summary>🔒 Data Security</summary>

- `.env` files are excluded by `.gitignore` — **never commit API keys** to the repository.
- **A Qiniu API key was leaked previously** (see historical commits): if you ever committed `.env` here, revoke the key in the Qiniu console and issue a new one immediately.
- `API_TOKEN` is a **global shared secret**, not a per-user/per-tenant system. Always set it in production.
- **Production enforces auth**: with `APP_ENV=production` and no `API_TOKEN`, the app refuses to start.
- **SSE stream auth**: when `API_TOKEN` is set, `/experiments/{id}/stream` also validates a `?token=` parameter (EventSource cannot set headers).

</details>

<details>
<summary>🗄️ Database</summary>

- v1 uses **SQLite** by default, which only supports **single-process writes**. On startup the app acquires an atomic writer lock per database file; stale locks left by abnormal exits are recovered automatically. Multi-instance deployments must switch to PostgreSQL:
  ```env
  DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/benchmarkops
  ```
- The database file `benchmarkops.db` is created automatically in `backend/` on first startup.

</details>

<details>
<summary>⚙️ Evaluation Runs</summary>

- With the default (`TASK_QUEUE_BACKEND=asyncio`), evaluations run **in-process**; restarting the process interrupts in-flight experiments. On startup, stale running/queued experiments are marked as failed.
- With `TASK_QUEUE_BACKEND=arq`, jobs are persisted in **Redis (ARQ)** and consumed by dedicated workers (`uv run arq app.worker.WorkerSettings`), supporting multiple workers/replicas and restart-safe jobs; startup recovery does not mislabel queued/running experiments.
- **Billing safety**: ARQ retries only transient failures that happen *before* calling a provider (e.g. database locks); 429s, quota exhaustion, and row-level errors are marked failed and retried manually.
- **Redis must have AOF persistence enabled** (already configured in Compose via `--appendonly yes`), otherwise Redis restarts lose queued jobs.
- **Multi-writer constraint**: the Compose default shares SQLite between backend and worker, which risks `database is locked`. For production, follow [docs/postgres-migration-guide.md](docs/postgres-migration-guide.md) or keep a single backend + task-side worker topology.
- Without `OPENROUTER_API_KEY` / `QINIU_API_KEY`, the **Mock provider** generates synthetic results for demo purposes.

</details>

<details>
<summary>📤 Dataset Uploads</summary>

- **Supported formats**: JSONL (recommended), JSON, CSV, TSV, XLSX; format is auto-detected by extension or can be set explicitly with `format`. Encodings: UTF-8 (incl. BOM), GBK/GB2312, UTF-16 (with BOM).
- **Limits**: single file ≤ 50 MB (`MAX_UPLOAD_BYTES`), ≤ 100,000 rows (`MAX_DATASET_ROWS`); **empty files are rejected**.
- **Async import**: `POST /datasets/import` is recommended for large files (returns an import job with row-level progress and supports `idempotency_key`); the synchronous `POST /datasets/upload` remains available.
- **Field conventions**: each row needs at least one input field and one expected-output field. Common expected-output keys: `answer` / `expected` / `label` / `output` / `target` / `ground_truth` (case-insensitive).
- **JSONL example**:
  ```jsonl
  {"question": "Compute 2 + 2.", "answer": "4"}
  {"question": "Translate to French: hello", "answer": "bonjour"}
  ```
- **CSV/TSV** must include a header row; **JSON** roots must be an array or contain a `data` / `rows` array.
- **Content validation**: file magic numbers are checked for `json/jsonl/xlsx`; `required_fields` / `field_types` enable per-row validation, with row-level errors reported in `error_rows`.
- **Nested fields**: prompt variables support path addressing (`{user.address.city}`, `{items.0}`); dict/list values render as JSON.
- **Multi-turn chat & few-shot**: with `structured_chat=true`, the `messages` field becomes the conversation chain and `examples` renders as Q/A few-shot examples; otherwise they are treated as ordinary input columns (backward compatible).
- **Versioning**: datasets are immutable; use `POST /datasets/{id}/versions` to create replacement/append versions and activate a rollback. Experiments snapshot the dataset version for reproducibility.
- **Sensitive fields**: declare `sensitive_fields` to redact previews and experiment results (`?mask_sensitive=true`).
- **Audit**: creation, versioning, activation, archiving, deletion, and import are audited (`GET /datasets/{id}/audit`).
- **Storage**: rows are stored in the database (with SHA-256 `content_hash`), not in object storage; large files increase DB size and backup time.
- **Field-role conflicts**: a column cannot map to multiple roles (input / expected / metadata) at once.

</details>

<details>
<summary>🖥️ Frontend SSR</summary>

- Next.js 14 Server Components cannot serialize non-plain objects (e.g. `Date`, custom class instances).
- `QueryClient` must be created inside a Client Component (see [react-query-client.tsx](frontend/src/lib/react-query-client.tsx)).
- If you hit "Classes or null prototypes are not supported", make sure no complex objects are passed from Server to Client Components.

</details>

<details>
<summary>ℹ️ Other Limitations</summary>

- **No multi-tenancy / no organization isolation**: all projects share the same database and token space.
- **Report export**: Markdown (`.md`) and PDF (`.pdf`) are supported; PDF relies on `weasyprint` and returns 501 when its system dependencies are missing.
- **Auth**: currently a simplified single-token scheme, not a full user/tenant system.

</details>

## Roadmap

| Phase | Plan |
|-------|------|
| **v2** | ARQ distributed task queue (✅ shipped), Redis cache, MinIO object storage |
| **v3** | Multi-tenancy / organization isolation, full RBAC permission system |
| **v4** | Multi-agent evaluation layer, custom evaluation agents |

## Contributing

Issues and pull requests are welcome! Please read [USAGE.md](USAGE.md) and [TESTING_GUIDE.md](TESTING_GUIDE.md) first and make sure tests pass locally.

## License

[MIT](LICENSE)

---

Built with ❤️ by the BenchmarkOps team.

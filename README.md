# BenchmarkOps

Enterprise AI **Evaluation & Benchmark Operations** platform. Manages Datasets,
Benchmarks, Prompts, Models, Experiments, Analytics and AI Reports around one
core workflow:

```
Project → Dataset → Benchmark → Prompt → Model → Experiment → Run → Compare → Report
```

## Stack (Iteration 1)

| Layer     | Tech |
|-----------|------|
| Frontend  | Next.js 16 (App Router) · TypeScript · Tailwind v4 · ECharts |
| Backend   | FastAPI · SQLAlchemy 2.0 (async) |
| Database  | SQLite (v1) → PostgreSQL (later) |
| Provider  | OpenRouter single gateway (falls back to deterministic Mock with no key) |
| Runner    | In-process threaded task queue (v1) → Celery (later) |

Reserved for later iterations: Redis, Celery, MinIO, multi-Agent layer.

## Architecture

Clean Architecture with strict layering:

```
Router (thin)  →  Service (business logic)  →  Repository (data access)  →  ORM
                        ↓
                  Provider registry (pluggable LLM gateways)
                  Evaluation engine (runner + metrics + task queue)
```

- Routers never touch the ORM — only Services.
- Services depend on Repository abstractions.
- Adding a provider/metric/module = new file, no changes to existing logic.

## Run

### Backend

```bash
cd backend
cp .env.example .env          # optionally set OPENROUTER_API_KEY
uv venv --python 3.11
uv pip install -e ".[dev]"
uv run uvicorn app.main:app --reload --port 8000
# → http://localhost:8000/docs   ·   http://localhost:8000/api/v1/health
```

### Frontend

```bash
cd frontend
cp .env.local.example .env.local   # NEXT_PUBLIC_API_BASE_URL
npm install
npm run dev
# → http://localhost:3000
```

## Tests

```bash
cd backend && uv run pytest
```

## Demo Data

Seed a runnable demo project end-to-end (Mock provider, no API key needed):

```bash
cd backend && uv run python -m app.seed
# creates a demo project, 8 models, a sample dataset, a benchmark, a prompt,
# runs two experiments, and generates a report.
```

Then open the frontend, open the **Demo: QA Benchmark** project, and view
**Compare** and **Reports**.

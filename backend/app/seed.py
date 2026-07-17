"""Demo seed for BenchmarkOps Iteration 1.

Builds a runnable demo project end-to-end through the real API layer
(TestClient), then runs two experiments with the Mock provider and
generates a report. Run with:  uv run python -m app.seed

Designed to run on SQLite with no API key: the sample dataset is chosen so
the deterministic Mock provider scores 1.0 on exact_match (known capitals
and simple arithmetic), exercising the whole chain offline.
"""
from __future__ import annotations

import io
import json
import time

from fastapi.testclient import TestClient

from app.main import create_app

API = "/api/v1"


def _post(client: TestClient, path: str, **body):
    r = client.post(f"{API}{path}", json=body)
    r.raise_for_status()
    return r.json()


def _seed(client: TestClient) -> None:
    print("Seeding BenchmarkOps demo data...")

    # 1. Project
    project = _post(client, "/projects/", name="Demo: QA Benchmark",
                    description="End-to-end demo of the BenchmarkOps workflow.")
    project_id = project["id"]
    print(f"  project  -> {project['name']} ({project_id[:8]})")

    # 2. Models
    seed = client.post(f"{API}/models/seed")
    seed.raise_for_status()
    n = seed.json()["seeded"]
    models = client.get(f"{API}/models/").json()
    print(f"  models   -> seeded {n}, total {len(models)}")

    # Pick two distinct seeded models for the comparison.
    m_a = next(m for m in models if m["name"] == "Claude 3.5 Haiku")
    m_b = next(m for m in models if m["name"] == "GPT-4o mini")

    # 3. Dataset (upload as JSONL). Pure arithmetic so the deterministic Mock
    # provider scores 1.0 on exact_match — giving a meaningful demo offline.
    rows = [
        {"question": "Compute 2 + 2.", "answer": "4"},
        {"question": "Compute 10 - 3.", "answer": "7"},
        {"question": "Compute 6 * 7.", "answer": "42"},
        {"question": "Compute 20 / 4.", "answer": "5"},
        {"question": "Compute 100 + 25.", "answer": "125"},
    ]
    payload = "\n".join(json.dumps(r) for r in rows).encode("utf-8")
    files = {
        "file": ("qa.jsonl", io.BytesIO(payload), "application/json"),
        "project_id": (None, project_id),
        "name": (None, "QA Sample"),
        "description": (None, "Arithmetic questions"),
        "format": (None, "jsonl"),
    }
    r = client.post(f"{API}/datasets/upload", files=files)
    r.raise_for_status()
    dataset = r.json()
    print(f"  dataset  -> {dataset['name']} ({dataset['row_count']} rows)")

    # 4. Benchmark (qa, exact_match)
    benchmark = _post(client, "/benchmarks/", project_id=project_id,
                      name="QA Exact Match", type="qa", metric="exact_match")
    print(f"  benchmark-> {benchmark['name']} ({benchmark['metric']})")

    # 5. Prompt
    prompt = _post(client, "/prompts/", project_id=project_id,
                   name="Answer directly",
                   template="Question: {question}\nAnswer with only the final result.",
                   description="Concise answering prompt.")
    print(f"  prompt   -> {prompt['name']} vars={prompt['variables']}")

    # 6 + 7. Experiments on two models
    exp_ids: list[str] = []
    for model in (m_a, m_b):
        exp = _post(client, "/experiments/", project_id=project_id,
                    name=f"Run: {model['name']}",
                    dataset_id=dataset["id"], benchmark_id=benchmark["id"],
                    prompt_id=prompt["id"], model_id=model["id"])
        exp_ids.append(exp["id"])
        # Fire the run.
        client.post(f"{API}/experiments/{exp['id']}/run").raise_for_status()
        print(f"  experiment-> {exp['name']} queued")

    # 8. Wait for both runs to finish (Mock provider is fast + synchronous-ish).
    for exp_id in exp_ids:
        for _ in range(50):
            status = client.get(f"{API}/experiments/{exp_id}").json()["status"]
            if status in ("completed", "failed"):
                break
            time.sleep(0.2)
        final = client.get(f"{API}/experiments/{exp_id}").json()
        acc = final["metrics"].get("accuracy", 0)
        print(f"    done    -> {final['name']}: {status} acc={acc}")

    # 9. Compare
    cmp = client.post(f"{API}/analytics/compare",
                      json={"experiment_ids": exp_ids}).json()
    print(f"  compare  -> labels={cmp['dimensions']['labels']}")

    # 10. Report (template fallback if no API key)
    report = _post(client, "/reports/generate", project_id=project_id,
                   experiment_ids=exp_ids, title="Demo Evaluation Report")
    print(f"  report   -> {report['title']} by {report['generated_by']}")

    print("\nSeed complete. Open the frontend, go to the Demo project, "
          "and view Compare / Reports.")


def main() -> None:
    # `with` keeps the anyio event loop alive across requests so the background
    # evaluation tasks scheduled by /run actually execute (same reason pytest
    # fixtures wrap the client in a context manager).
    with TestClient(create_app()) as client:
        _seed(client)


if __name__ == "__main__":
    main()

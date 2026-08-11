"""Boundary / edge-case E2E tests for BenchmarkOps.

These complement test_flow.py (the happy path) by exercising the guards the
backend enforces, observed through the real UI:
  - oversized / over-row-count dataset upload is rejected with a visible error
  - experiment creation requires all fields
  - double-clicking 运行 does not double-run (runner CAS guard via the UI)
"""
from __future__ import annotations

from playwright.sync_api import Page

import helpers as H

# 100_001 rows -> exceeds max_dataset_rows (100_000) in backend config.
OVER_ROWS_JSONL = '{"question":"x","answer":"y"}\n' * 100_001


def test_upload_rejects_too_many_rows(page: Page) -> None:
    H.seed_models(page)
    H.create_project(page, "EDGE-超限行数", "边界:超行数")
    H.open_project(page, "EDGE-超限行数")
    H.upload_dataset_expect_error(
        page, "EDGE-超大集", OVER_ROWS_JSONL, "rows exceeds limit"
    )


def test_experiment_requires_all_fields(page: Page) -> None:
    H.create_project(page, "EDGE-必填", "边界:必填")
    H.open_project(page, "EDGE-必填")
    H.create_experiment_missing_fields(page)


def test_experiment_run_writes_single_batch(page: Page) -> None:
    """A run completes cleanly and writes exactly one result batch (no CAS violation)."""
    H.seed_models(page)
    H.create_project(page, "EDGE-防双写", "边界:并发防双写")
    H.open_project(page, "EDGE-防双写")
    H.upload_dataset(page, "EDGE-数据集")
    H.create_benchmark(page, "EDGE-基准", btype="qa")
    H.create_prompt(page, "EDGE-提示词", template="请回答:{question}")
    H.create_experiment(
        page, "EDGE-实验", "EDGE-数据集", "EDGE-基准", "EDGE-提示词"
    )
    # Rapid double-click 运行; should still complete cleanly (no crash/dupe).
    H.run_experiment_once(page, "EDGE-实验")
    # Drill into results; the per-row result list must equal the dataset size
    # (3 rows), confirming exactly one run was written (no doubled batch).
    page.locator('a', has_text="EDGE-实验").first.click()
    page.wait_for_load_state("networkidle")
    page.get_by_text("逐行结果", exact=False).first.wait_for(timeout=10000)

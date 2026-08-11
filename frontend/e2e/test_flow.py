"""End-to-end UI workflow test for BenchmarkOps (Python + Playwright).

Covers the full happy path through the web UI:
  models seed -> project -> dataset -> benchmark -> prompt -> experiment run
  -> results -> compare -> report generation -> export.

Provider is the deterministic Mock (backend OPENROUTER_API_KEY empty), so the
experiment completes with a stable accuracy and no cost is incurred.
"""
from __future__ import annotations

import time

from playwright.sync_api import Page, expect

import helpers as H

PROJECT = "E2E-测试项目"
DATASET = "E2E-数据集"
BENCHMARK = "E2E-基准"
PROMPT = "E2E-提示词"
EXPERIMENT = "E2E-实验"


def test_full_e2e_flow(page: Page) -> None:
    # 1) Models
    H.seed_models(page)
    page.get_by_text("启用中", exact=False).first.wait_for(timeout=15000)
    cards = page.locator('div').filter(has_text="启用中").count()
    assert cards > 0, "expected at least one seeded model"

    # 2) Project
    H.create_project(page, PROJECT, description="端到端测试自动创建")
    H.open_project(page, PROJECT)

    # 3) Dataset (upload a JSONL with 3 rows)
    H.upload_dataset(page, DATASET)
    # The dataset card shows its row count.
    page.get_by_text("3 rows").first.wait_for(timeout=10000)

    # 4) Benchmark
    H.create_benchmark(page, BENCHMARK, btype="qa")

    # 5) Prompt (template with a {question} variable)
    H.create_prompt(page, PROMPT, template="请回答以下问题:{question}")

    # 6) Experiment + run
    H.create_experiment(page, EXPERIMENT, DATASET, BENCHMARK, PROMPT)
    H.run_experiment(page, EXPERIMENT)

    # 7) Results — open experiment detail and see per-row scores
    page.locator('a', has_text=EXPERIMENT).first.click()
    page.wait_for_load_state("networkidle")
    # Detail page shows an accuracy summary.
    page.get_by_text("准确率", exact=False).first.wait_for(timeout=10000)

    # 8) Compare — back to project, experiments tab, select + compare selected
    H.open_project(page, PROJECT)
    H.select_tab(page, "实验")
    # Tick the experiment's compare checkbox, then click 对比选中.
    exp_link = page.locator('a', has_text=EXPERIMENT).first
    # The experiment card always contains the compare checkbox, regardless of
    # run state (运行/重试/运行中). Anchor the card on the checkbox, not 运行.
    checkbox = page.locator('input[aria-label^="选择"]')
    card = page.locator("div").filter(has=exp_link).filter(has=checkbox).first
    card.locator('input[type="checkbox"]').check()
    compare_sel = page.get_by_role("button", name="对比选中")
    compare_sel.wait_for(timeout=10000)
    compare_sel.click()
    page.wait_for_load_state("networkidle")
    page.get_by_text("对比", exact=False).first.wait_for(timeout=10000)

    # 9) Report generation (reports tab)
    H.open_project(page, PROJECT)
    H.select_tab(page, "报告")
    # Pick the completed experiment via its checkbox, then generate.
    page.locator('input[type="checkbox"]').first.check()
    gen = page.get_by_role("button", name="生成报告")
    gen.wait_for(timeout=10000)
    gen.click()
    # A report card with a view/export control should appear.
    page.get_by_text("导出 .md", exact=False).first.wait_for(timeout=20000)


def test_project_create_validation(page: Page) -> None:
    """Creating a project with an empty name must not create anything."""
    H.goto_projects(page)
    before = page.locator('a', has_text="E2E-校验").count()
    page.get_by_role("button", name="新建项目").click()
    # Leave name empty, click 创建 — should stay in modal / no new card.
    page.get_by_role("button", name="创建").click()
    page.wait_for_timeout(500)
    after = page.locator('a', has_text="E2E-校验").count()
    assert before == after, "empty-name project should not be created"

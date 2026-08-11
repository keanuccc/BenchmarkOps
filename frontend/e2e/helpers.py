"""Reusable UI helpers for the BenchmarkOps E2E flow.

The app is a Chinese-language UI. We locate controls by their visible text
(labels like "新建项目", buttons like "创建"/"运行"). Dropdown options are
selected by their visible label so the helper is resilient to ordering.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from playwright.sync_api import Page

DATASET_JSONL = (
    '{"question":"2+2等于几?","answer":"4"}\n'
    '{"question":"3*3等于几?","answer":"9"}\n'
    '{"question":"10-6等于几?","answer":"4"}\n'
)


def goto_projects(page: Page) -> None:
    page.locator('a[href="/projects"]').first.click()
    page.wait_for_load_state("networkidle")


def seed_models(page: Page) -> None:
    """Open the model center and click 初始化模型 (idempotent)."""
    page.locator('a[href="/models"]').first.click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="初始化模型").click()
    page.get_by_text("上下文", exact=False).first.wait_for(timeout=15000)


def seed_mock_model(page: Page) -> str:
    """Ensure an offline mock model exists for experiments (idempotent).

    The seeded OpenRouter-style models need a real OpenRouter key; the E2E
    backend runs in mock mode, so experiments must use a mock model.
    """
    resp = page.request.post(
        "http://localhost:8001/api/v1/models/",
        data={
            "name": "E2E Mock",
            "provider": "mock",
            "model_id": "e2e-mock",
            "context_length": 8192,
            "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0},
            "capabilities": ["qa", "coding"],
        },
    )
    assert resp.ok or resp.status == 409, f"seed mock model failed: {resp.status}"
    models = page.request.get("http://localhost:8001/api/v1/models/").json()["items"]
    mock = next(m for m in models if m["model_id"] == "e2e-mock")
    return mock["id"]


def create_project(page: Page, name: str, description: str = "") -> None:
    goto_projects(page)
    page.get_by_role("button", name="新建项目").click()
    page.get_by_placeholder("项目名称").fill(name)
    if description:
        page.get_by_placeholder("描述（可选）").fill(description)
    page.get_by_role("button", name="创建").click()
    page.get_by_text(name, exact=False).first.wait_for(timeout=10000)


def open_project(page: Page, name: str) -> None:
    goto_projects(page)
    page.get_by_text(name, exact=True).first.click()
    page.wait_for_load_state("networkidle")
    page.get_by_text(name, exact=False).first.wait_for(timeout=10000)


def select_tab(page: Page, tab_name: str) -> None:
    """tab_name is one of 数据集/基准/提示词/实验/报告."""
    page.get_by_role("button", name=tab_name).click()
    page.wait_for_load_state("networkidle")


def upload_dataset(page: Page, name: str, jsonl: str = DATASET_JSONL) -> None:
    select_tab(page, "数据集")
    with tempfile.NamedTemporaryFile(
        "w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        f.write(jsonl)
        path = f.name
    try:
        # The 名称 field has a <label> but no placeholder; target the first
        # text input of the upload form (before the file input).
        # The 名称 field is an untyped <input> (no placeholder); target the
        # first non-file input of the upload form.
        form = page.get_by_role("button", name="导入").locator("xpath=ancestor::form")
        form.locator('input:not([type="file"])').first.fill(name)
        page.locator('input[type="file"]').set_input_files(path)
        page.get_by_role("button", name="导入").click()
        page.get_by_text(name, exact=False).first.wait_for(timeout=10000)
    finally:
        Path(path).unlink(missing_ok=True)


def create_benchmark(page: Page, name: str, btype: str = "qa") -> None:
    select_tab(page, "基准")
    # 名称 field has only a <label>, no placeholder.
    form = page.get_by_role("button", name="创建").locator("xpath=ancestor::form")
    form.locator('input:not([type="file"])').first.fill(name)
    page.locator('select').first.select_option(btype)
    # Leave metric = 自动 (default) to exercise the default-metric path.
    page.get_by_role("button", name="创建").click()
    page.get_by_text(name, exact=False).first.wait_for(timeout=10000)


def create_prompt(page: Page, name: str, template: str) -> None:
    select_tab(page, "提示词")
    page.get_by_placeholder("提示词名称").fill(name)
    page.get_by_placeholder(
        "模板 — 使用 {变量} 占位符,例如:回答问题:{question}"
    ).fill(template)
    page.get_by_role("button", name="创建").click()
    page.get_by_text(name, exact=False).first.wait_for(timeout=10000)


def create_experiment(
    page: Page,
    name: str,
    dataset_name: str,
    benchmark_name: str,
    prompt_name: str,
) -> None:
    """Fill the experiment form (model = first available) and create it."""
    select_tab(page, "实验")
    page.get_by_placeholder("实验名称").fill(name)
    # Options render as "name (row_count)" / "name (metric)" etc., so select
    # by index (0 = the 选择… placeholder, 1 = first real item).
    selects = page.locator('select')
    selects.nth(0).select_option(index=1)  # dataset
    selects.nth(1).select_option(index=1)  # benchmark
    selects.nth(2).select_option(index=1)  # prompt
    mock_model_id = seed_mock_model(page)
    selects.nth(3).select_option(value=mock_model_id)  # model (offline mock)
    page.get_by_role("button", name="创建实验").click()
    page.get_by_text(name, exact=False).first.wait_for(timeout=10000)


def run_experiment(page: Page, name: str) -> None:
    """Click 运行 on the experiment card and wait for completion."""
    exp_link = page.locator('a', has_text=name).first
    exp_link.wait_for(timeout=10000)
    # The experiment card is the div that both contains the name link and a 运行
    # button (Card renders utility classes, not a literal "Card" class).
    card = (
        page.locator("div")
        .filter(has=exp_link)
        .filter(has=page.get_by_role("button", name="运行"))
        .first
    )
    card.get_by_role("button", name="运行").click()
    # The UI auto-polls; wait for the "acc:" summary to appear (completed state).
    page.get_by_text("acc:", exact=False).first.wait_for(timeout=60000)


def upload_dataset_expect_error(
    page: Page, name: str, jsonl: str, error_substr: str
) -> None:
    """Upload a dataset that the backend must reject; assert the error surfaces."""
    select_tab(page, "数据集")
    with tempfile.NamedTemporaryFile(
        "w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        f.write(jsonl)
        path = f.name
    try:
        form = page.get_by_role("button", name="导入").locator("xpath=ancestor::form")
        form.locator('input:not([type="file"])').first.fill(name)
        page.locator('input[type="file"]').set_input_files(path)
        page.get_by_role("button", name="导入").click()
        # The UI shows the backend error message verbatim.
        page.get_by_text(error_substr, exact=False).first.wait_for(timeout=10000)
        # No dataset card should have been created.
        assert (
            page.get_by_text(name, exact=False).count() == 0
        ), f"rejected dataset '{name}' should not appear"
    finally:
        Path(path).unlink(missing_ok=True)


def create_experiment_missing_fields(page: Page) -> None:
    """Submit the experiment form with no fields filled; assert validation error."""
    select_tab(page, "实验")
    page.get_by_role("button", name="创建实验").click()
    page.get_by_text("所有字段均为必填项", exact=False).first.wait_for(timeout=10000)


def run_experiment_once(page: Page, name: str) -> None:
    """Click 运行 and wait for the experiment to reach a completed terminal state.

    The runner's CAS guard (backend test_run_race) guarantees a single result
    batch is written; here we confirm the UI surfaces a clean completed run
    rather than crashing or leaving the experiment stuck.
    """
    exp_link = page.locator('a', has_text=name).first
    exp_link.wait_for(timeout=10000)
    card = (
        page.locator("div")
        .filter(has=exp_link)
        .filter(has=page.get_by_role("button", name="运行"))
        .first
    )
    card.get_by_role("button", name="运行").click()
    page.get_by_text("acc:", exact=False).first.wait_for(timeout=60000)

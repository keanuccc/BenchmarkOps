"""New-feature UI interaction tests: organization manager, scheduled reports,
webhook panel (previously only render-smoked)."""
from __future__ import annotations

import json
import time

from playwright.sync_api import Page


def _api(page: Page, method: str, path: str, body=None):
    resp = page.request.fetch(
        f"http://localhost:8001/api/v1{path}",
        method=method,
        data=json.dumps(body) if body is not None else None,
        headers={"Content-Type": "application/json"} if body is not None else None,
    )
    assert resp.ok, f"{method} {path} -> {resp.status} {resp.text()[:200]}"
    return resp.json()


def _seed_project(page: Page) -> str:
    """Create project + dataset + benchmark + prompt + mock model + experiment."""
    pid = _api(page, "POST", "/projects/", {"name": "NF-项目"})["id"]
    rows = '{"question":"计算 2+2","answer":"4","category":"c"}\n' * 3
    import io

    boundary = "----nf"
    parts = []
    for f, v in {
        "project_id": pid, "name": "NF-数据", "format": "jsonl", "task_type": "qa",
        "input_fields": '["question"]', "expected_fields": '["answer"]',
        "metadata_fields": '["category"]',
    }.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{f}"\r\n\r\n{v}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="d.jsonl"\r\n'
        f"Content-Type: application/jsonl\r\n\r\n".encode() + rows.encode() + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    resp = page.request.post(
        "http://localhost:8001/api/v1/datasets/upload",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert resp.ok, resp.text()[:200]
    ds_id = resp.json()["id"]
    bench = _api(page, "POST", "/benchmarks/", {"project_id": pid, "name": "NF-基准", "type": "qa", "metric": "exact_match_ci"})
    prompt = _api(page, "POST", "/prompts/", {"project_id": pid, "name": "NF-提示词", "template": "问题：{question}\n答案："})
    model_resp = page.request.fetch(
        "http://localhost:8001/api/v1/models/",
        method="POST",
        data=json.dumps({
        "name": "NF Mock", "provider": "mock", "model_id": "nf-mock",
        "context_length": 8192, "pricing": {}, "capabilities": ["qa"],
        }),
        headers={"Content-Type": "application/json"},
    )
    if model_resp.status == 409:
        models = _api(page, "GET", "/models/")["items"]
        model = next(m for m in models if m["model_id"] == "nf-mock")
    else:
        assert model_resp.ok, model_resp.text()[:200]
        model = model_resp.json()
    exp = _api(page, "POST", "/experiments/", {
        "project_id": pid, "name": "NF-实验", "dataset_id": ds_id,
        "benchmark_id": bench["id"], "prompt_id": prompt["id"], "model_id": model["id"],
    })
    _api(page, "POST", f"/experiments/{exp['id']}/run", {})
    for _ in range(60):
        status = _api(page, "GET", f"/experiments/{exp['id']}")["status"]
        if status in ("completed", "partial", "failed"):
            break
        time.sleep(1)
    return pid


def test_organization_manager_full_flow(page: Page) -> None:
    """Create an organization from the settings UI and verify the scoped key works."""
    page.goto("http://localhost:3001/settings", wait_until="networkidle")
    page.wait_for_timeout(1500)
    page.get_by_placeholder("组织名称（如：某某科技）").fill("UI 测试组织")
    page.get_by_role("button", name="创建组织").click()
    # Owner key is shown once.
    page.get_by_text("只显示这一次", exact=False).first.wait_for(timeout=10000)
    body = page.inner_text("body")
    assert "bmops_" in body, "owner key should be visible"
    assert "组织：" in body or "UI 测试组织" in body
    # Now create a project under the org (request carries the org key).
    page.goto("http://localhost:3001/projects", wait_until="networkidle")
    page.get_by_role("button", name="新建项目").click()
    page.get_by_placeholder("项目名称").fill("组织内项目")
    page.get_by_role("button", name="创建").click()
    page.get_by_text("组织内项目", exact=False).first.wait_for(timeout=10000)
    # org key exists in localStorage after creation
    assert page.evaluate("() => localStorage.getItem('benchmarkops_org_key')") is not None


def test_scheduled_report_panel_creates_entry(page: Page) -> None:
    pid = _seed_project(page)
    page.goto(f"http://localhost:3001/projects/{pid}", wait_until="networkidle")
    page.wait_for_timeout(1500)
    # 报告 tab
    for b in page.get_by_role("button").all():
        if (b.inner_text() or "").strip().startswith("报告"):
            b.click()
            break
    page.wait_for_load_state("networkidle")
    page.get_by_placeholder("报告名称（如：每周模型质量报告）").fill("UI 定时报告")
    # 勾选定时报告面板中的实验（第二个 checkbox；第一个属于上方生成报告区块）
    checkbox = page.locator('input[type="checkbox"]:visible').nth(1)
    checkbox.check()
    # 定时报告面板在报告页签中位于 Webhook 面板之前，取第一个“创建”。
    page.get_by_role("button", name="创建").first.click()
    page.get_by_text("UI 定时报告", exact=False).first.wait_for(timeout=10000)


def test_webhook_panel_creates_and_tests(page: Page) -> None:
    pid = _seed_project(page)
    page.goto(f"http://localhost:3001/projects/{pid}", wait_until="networkidle")
    page.wait_for_timeout(1500)
    for b in page.get_by_role("button").all():
        if (b.inner_text() or "").strip().startswith("报告"):
            b.click()
            break
    page.wait_for_load_state("networkidle")
    page.get_by_placeholder("名称（如：CI 回归通知）").fill("UI Webhook")
    page.get_by_placeholder("https://example.com/hook").fill("http://127.0.0.1:9/hook")
    page.get_by_role("button", name="创建").last.click()
    page.get_by_text("UI Webhook", exact=False).first.wait_for(timeout=10000)
    # 测试按钮（送达失败提示，但面板操作链路正常）
    page.get_by_title("发送测试请求").first.click()
    page.get_by_text("送达失败", exact=False).first.wait_for(timeout=10000)

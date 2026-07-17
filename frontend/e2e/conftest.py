"""Pytest fixtures for the BenchmarkOps frontend E2E suite.

Assumptions (see README.md):
  - The Next dev server is already running and reachable (default
    http://localhost:3000). We do NOT start/stop it here so the suite can be
    run against a live dev server without fighting your own session.
  - The backend runs with OPENROUTER_API_KEY empty, so experiments execute on
    the deterministic Mock provider (free, deterministic, no API key needed).

Run:
    pytest e2e/ -v
Override base URL:
    BASE_URL=http://localhost:3001 pytest e2e/ -v
"""
from __future__ import annotations

import os

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

BASE_URL = os.environ.get("BASE_URL", "http://localhost:3000").rstrip("/")


@pytest.fixture(scope="session")
def browser() -> Browser:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(base_url=BASE_URL)
    yield ctx
    ctx.close()


@pytest.fixture
def page(context: BrowserContext) -> Page:
    page = context.new_page()
    page.goto("/")
    page.wait_for_load_state("networkidle")
    yield page
    page.close()

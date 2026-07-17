"""Minimal global-token auth tests.

Verifies the conservative auth model:
- demo mode (empty settings.api_token) -> every write passes with no token.
- enforced mode (settings.api_token set) -> missing/wrong token -> 401,
  correct Bearer token -> 200.
"""
from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.fixture()
def auth_client(client, monkeypatch):
    # Enforce auth for these tests.
    monkeypatch.setattr(settings, "api_token", "secret")
    yield client
    monkeypatch.setattr(settings, "api_token", "")


@pytest.fixture()
def demo_client(client, monkeypatch):
    # Ensure demo mode regardless of env.
    monkeypatch.setattr(settings, "api_token", "")
    yield client


def test_demo_mode_allows_write_without_token(demo_client):
    r = demo_client.post(
        "/api/v1/projects", json={"name": "p", "status": "active"}
    )
    assert r.status_code == 201


def test_enforced_missing_token_returns_401(auth_client):
    r = auth_client.post(
        "/api/v1/projects", json={"name": "p", "status": "active"}
    )
    assert r.status_code == 401
    assert r.json() == {
        "error": {"code": "unauthorized", "message": "Missing or malformed Authorization header"}
    }


def test_enforced_wrong_token_returns_401(auth_client):
    r = auth_client.post(
        "/api/v1/projects",
        json={"name": "p", "status": "active"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401
    assert r.json() == {
        "error": {"code": "unauthorized", "message": "Invalid API token"}
    }


def test_enforced_correct_token_returns_201(auth_client):
    r = auth_client.post(
        "/api/v1/projects",
        json={"name": "p", "status": "active"},
        headers={"Authorization": "Bearer secret"},
    )
    assert r.status_code == 201


def test_enforced_protects_delete(auth_client):
    # Need a project first (using correct token).
    created = auth_client.post(
        "/api/v1/projects",
        json={"name": "del", "status": "active"},
        headers={"Authorization": "Bearer secret"},
    )
    pid = created.json()["id"]
    # Delete without token -> 401.
    r = auth_client.delete(f"/api/v1/projects/{pid}")
    assert r.status_code == 401
    # Delete with token -> 204.
    r2 = auth_client.delete(
        f"/api/v1/projects/{pid}", headers={"Authorization": "Bearer secret"}
    )
    assert r2.status_code == 204

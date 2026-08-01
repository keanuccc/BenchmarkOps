"""SSE progress stream must enforce the API token when auth is enabled.

The frontend already sends ``?token=`` (EventSource cannot set headers), but the
backend previously ignored it entirely. These tests pin the intended contract:
when ``API_TOKEN`` is configured, the stream requires the exact token.
"""
from __future__ import annotations

from app.core.config import settings


def test_sse_rejects_missing_token_when_auth_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "secret-token")
    resp = client.get("/api/v1/experiments/does-not-exist/stream")
    assert resp.status_code == 401


def test_sse_rejects_wrong_token_when_auth_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "secret-token")
    resp = client.get(
        "/api/v1/experiments/does-not-exist/stream", params={"token": "wrong"}
    )
    assert resp.status_code == 401


def test_sse_accepts_token_when_auth_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "secret-token")
    resp = client.get(
        "/api/v1/experiments/does-not-exist/stream",
        params={"token": "secret-token"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


def test_sse_open_without_token_when_auth_disabled(client):
    resp = client.get("/api/v1/experiments/does-not-exist/stream")
    assert resp.status_code == 200

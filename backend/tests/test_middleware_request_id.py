"""The request-ID middleware must add a per-request X-Request-ID header."""
from __future__ import annotations


def test_health_response_has_request_id(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert "x-request-id" in resp.headers
    assert len(resp.headers["x-request-id"]) == 12


def test_request_id_differs_between_requests(client):
    first = client.get("/api/v1/health").headers["x-request-id"]
    second = client.get("/api/v1/health").headers["x-request-id"]
    assert first != second

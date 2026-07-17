"""Tests for the global 500 catch-all exception handler.

We register a route that raises a non-DomainError exception, then assert the
response is a generic 500 with no internal detail leaked in the body.

Note: TestClient re-raises server exceptions by default, so we construct our own
client with ``raise_server_exceptions=False`` to exercise the handler path.
"""
from __future__ import annotations

from fastapi import APIRouter
from starlette.testclient import TestClient

from app.core.exceptions import register_exception_handlers
from app.main import app

router = APIRouter()


@router.get("/__test_boom")
async def boom() -> None:
    raise RuntimeError("secret: SELECT * FROM users WHERE password='x'; /etc/passwd")


app.include_router(router)
register_exception_handlers(app)


def test_unhandled_exception_returns_generic_500():
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/__test_boom")
    assert r.status_code == 500
    assert r.json() == {
        "error": {"code": "internal_error", "message": "Internal server error"}
    }


def test_unhandled_exception_does_not_leak_stack():
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/__test_boom")
    text = r.text
    assert "SELECT" not in text
    assert "/etc/passwd" not in text
    assert "RuntimeError" not in text
    assert "Traceback" not in text


def test_domain_error_still_works(client):
    # Sanity check: the app still serves normal routes and DomainError stays intact.
    r = client.get("/api/v1/health")
    assert r.status_code == 200

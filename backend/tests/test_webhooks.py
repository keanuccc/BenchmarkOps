"""Tests for webhook subscriptions, signing, and delivery."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.core.database import AsyncSessionLocal
from app.models.project import Project
from app.models.webhook import WebhookSubscription
from app.services.webhook_service import WebhookService, _sign


def test_signature_is_stable_hmac():
    sig1 = _sign("secret", b'{"a": 1}')
    sig2 = _sign("secret", b'{"a": 1}')
    sig3 = _sign("other", b'{"a": 1}')
    assert sig1 == sig2
    assert sig1 != sig3
    assert len(sig1) == 64


async def test_webhook_crud_scoped_to_project():
    async with AsyncSessionLocal() as session:
        project = Project(name="hook-p")
        session.add(project)
        await session.flush()
        service = WebhookService(session)
        created = await service.create(
            __import__(
                "app.schemas.webhook", fromlist=["WebhookCreate"]
            ).WebhookCreate(
                project_id=project.id,
                name="CI",
                url="https://example.com/hook",
                secret="s3cret",
                events=["experiment.completed"],
            )
        )
        assert created.events == ["experiment.completed"]
        listed = await service.list(project.id)
        assert len(listed) == 1
        await service.delete(created.id)
        await session.commit()


def test_delivery_posts_payload_and_signature():
    received: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            received["body"] = self.rfile.read(length)
            received["sig"] = self.headers.get("X-BenchmarkOps-Signature", "")
            received["event"] = self.headers.get("X-BenchmarkOps-Event", "")
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):  # noqa: ARG002
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    import asyncio

    from app.services.webhook_service import _deliver

    hook = WebhookSubscription(
        id="hook-1",
        organization_id=None,
        project_id="p",
        name="t",
        url=f"http://127.0.0.1:{port}/hook",
        secret="sek",
        events=["experiment.completed"],
        is_active=True,
    )
    ok = asyncio.run(
        _deliver(hook, "experiment.completed", {"event": "experiment.completed"})
    )
    server.shutdown()
    assert ok is True
    assert json.loads(received["body"])["event"] == "experiment.completed"
    assert received["event"] == "experiment.completed"
    assert received["sig"] == _sign("sek", received["body"])

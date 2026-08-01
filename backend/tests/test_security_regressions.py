"""Regression tests for security fixes.

Covers two P0 findings:

1. Backup download path traversal (``GET /db/backup/{filename}``): only files
   matching ``benchmarkops_<timestamp>.db`` and resolving inside ``./backups``
   may be served; anything else is 400, a missing valid file is 404.

2. API-token bootstrap guard (``POST /settings/api-token``): when auth is
   disabled the token can no longer be installed or removed over HTTP, and an
   enabled admin's token change applies to the running process immediately
   (instead of only after a restart).
"""
from __future__ import annotations

import pytest

from app.api.v1.routes import settings as settings_routes
from app.core.config import settings


@pytest.fixture()
def demo_client(client, monkeypatch):
    # Demo mode: no auth token configured.
    monkeypatch.setattr(settings, "api_token", "")
    yield client


@pytest.fixture()
def auth_client(client, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "secret")
    yield client
    monkeypatch.setattr(settings, "api_token", "")


# --- Backup download --------------------------------------------------------


def test_backup_download_rejects_path_traversal(client, monkeypatch, tmp_path):
    """URL-encoded ``../`` must not escape the backups directory."""
    monkeypatch.setattr(settings, "api_token", "")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "backups").mkdir()
    (tmp_path / "secret.txt").write_text("TOP SECRET", encoding="utf-8")

    r = client.get("/api/v1/db/backup/..%2Fsecret.txt")
    # The router may reject the decoded ``/`` outright (404) or our handler may
    # reject the filename (400); either way the file must never be served.
    assert r.status_code in (400, 404)
    assert "TOP SECRET" not in r.text

    # Windows-style separator is equally rejected.
    r2 = client.get("/api/v1/db/backup/..%5Csecret.txt")
    assert r2.status_code == 400


def test_backup_download_rejects_unexpected_filename(client, monkeypatch, tmp_path):
    """A real file in ./backups that is not a BenchmarkOps backup is refused."""
    monkeypatch.setattr(settings, "api_token", "")
    monkeypatch.chdir(tmp_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "other.db").write_text("x", encoding="utf-8")

    r = client.get("/api/v1/db/backup/other.db")
    assert r.status_code == 400


def test_backup_download_missing_file_returns_404(client, monkeypatch, tmp_path):
    """A valid-looking but absent backup yields 404, not a 500."""
    monkeypatch.setattr(settings, "api_token", "")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "backups").mkdir()

    r = client.get("/api/v1/db/backup/benchmarkops_20260801_000000.db")
    assert r.status_code == 404


def test_backup_download_serves_valid_backup(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "api_token", "")
    monkeypatch.chdir(tmp_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "benchmarkops_20260801_000000.db").write_text(
        "snapshot-data", encoding="utf-8"
    )

    r = client.get("/api/v1/db/backup/benchmarkops_20260801_000000.db")
    assert r.status_code == 200
    assert r.content == b"snapshot-data"


# --- API-token bootstrap guard ----------------------------------------------


def test_token_cannot_be_set_when_auth_disabled(demo_client):
    """An unauthenticated caller must not be able to install a platform token."""
    r = demo_client.post(
        "/api/v1/settings/api-token", json={"token": "attacker-token"}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert settings.api_token == ""


def test_token_cannot_be_removed_when_auth_disabled(demo_client):
    r = demo_client.post("/api/v1/settings/api-token", json={"token": ""})
    assert r.status_code == 401


def test_token_change_applies_immediately_when_enforced(auth_client, monkeypatch, tmp_path):
    """An authenticated admin's token change works, persists to .env, and takes
    effect in the running process without a restart."""
    env_file = tmp_path / ".env"
    monkeypatch.setattr(settings_routes, "_get_env_path", lambda: env_file)

    r = auth_client.post(
        "/api/v1/settings/api-token",
        json={"token": "newsecret"},
        headers={"Authorization": "Bearer secret"},
    )
    assert r.status_code == 200
    assert settings.api_token == "newsecret"
    assert "API_TOKEN=newsecret" in env_file.read_text(encoding="utf-8")

    # Old token is rejected, new token is accepted immediately.
    r_old = auth_client.post(
        "/api/v1/projects",
        json={"name": "p"},
        headers={"Authorization": "Bearer secret"},
    )
    assert r_old.status_code == 401

    r_new = auth_client.post(
        "/api/v1/projects",
        json={"name": "p"},
        headers={"Authorization": "Bearer newsecret"},
    )
    assert r_new.status_code == 201

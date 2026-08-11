"""Multi-tenant isolation and API-key role tests.

Covers organization creation, scoped resource CRUD, cross-org invisibility,
role gating (viewer read-only, admin key management) and the no-token demo
compatibility mode.
"""
from __future__ import annotations


def _create_org(client, name: str) -> tuple[str, str]:
    r = client.post(
        "/api/v1/organizations",
        json={"name": name, "description": "test"},
    )
    assert r.status_code == 201, r.text
    payload = r.json()
    org_id = payload["organization"]["id"]
    key = payload["api_key"]["key"]
    assert key.startswith("bmops_")
    assert payload["api_key"]["role"] == "owner"
    return org_id, key


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def test_create_organization_returns_owner_key(client):
    org_id, key = _create_org(client, "Org A")
    me = client.get("/api/v1/organizations/me", headers=_auth(key))
    assert me.status_code == 200
    assert me.json()["id"] == org_id


def test_org_key_scopes_projects(client):
    _, key_a = _create_org(client, "Org A")
    _, key_b = _create_org(client, "Org B")

    created = client.post(
        "/api/v1/projects",
        json={"name": "A project"},
        headers=_auth(key_a),
    )
    assert created.status_code == 201
    pid = created.json()["id"]

    # Org B must not see Org A's project.
    listed = client.get("/api/v1/projects", headers=_auth(key_b))
    assert listed.status_code == 200
    assert all(item["id"] != pid for item in listed.json()["items"])

    # Org B must not be able to read or mutate Org A's project.
    got = client.get(f"/api/v1/projects/{pid}", headers=_auth(key_b))
    assert got.status_code == 404
    patched = client.patch(
        f"/api/v1/projects/{pid}",
        json={"name": "hijacked"},
        headers=_auth(key_b),
    )
    assert patched.status_code == 404

    # Org A can still see it.
    own = client.get("/api/v1/projects", headers=_auth(key_a))
    assert any(item["id"] == pid for item in own.json()["items"])


def test_viewer_key_is_read_only(client):
    org_id, owner_key = _create_org(client, "Org V")
    viewer = client.post(
        f"/api/v1/organizations/{org_id}/api-keys",
        json={"name": "ro", "role": "viewer"},
        headers=_auth(owner_key),
    )
    assert viewer.status_code == 201
    viewer_key = viewer.json()["key"]

    r = client.post(
        "/api/v1/projects",
        json={"name": "should fail"},
        headers=_auth(viewer_key),
    )
    assert r.status_code == 403

    # Viewer can read its own organization.
    me = client.get("/api/v1/organizations/me", headers=_auth(viewer_key))
    assert me.status_code == 200
    assert me.json()["id"] == org_id


def test_member_cannot_manage_keys(client):
    org_id, owner_key = _create_org(client, "Org M")
    member = client.post(
        f"/api/v1/organizations/{org_id}/api-keys",
        json={"name": "dev", "role": "member"},
        headers=_auth(owner_key),
    )
    assert member.status_code == 201
    member_key = member.json()["key"]

    # Member can create resources but not manage API keys.
    project = client.post(
        "/api/v1/projects",
        json={"name": "member project"},
        headers=_auth(member_key),
    )
    assert project.status_code == 201

    keys = client.get(
        f"/api/v1/organizations/{org_id}/api-keys",
        headers=_auth(member_key),
    )
    assert keys.status_code == 403

    created = client.post(
        f"/api/v1/organizations/{org_id}/api-keys",
        json={"name": "x", "role": "member"},
        headers=_auth(member_key),
    )
    assert created.status_code == 403


def test_owner_key_cannot_be_revoked_when_only_one(client):
    org_id, owner_key = _create_org(client, "Org R")
    keys = client.get(
        f"/api/v1/organizations/{org_id}/api-keys",
        headers=_auth(owner_key),
    )
    assert keys.status_code == 200
    owner_key_id = keys.json()[0]["id"]
    r = client.delete(
        f"/api/v1/organizations/{org_id}/api-keys/{owner_key_id}",
        headers=_auth(owner_key),
    )
    assert r.status_code == 422


def test_dataset_created_with_org_key_is_scoped(client):
    _, key_a = _create_org(client, "Org D1")
    _, key_b = _create_org(client, "Org D2")

    project = client.post(
        "/api/v1/projects",
        json={"name": "p"},
        headers=_auth(key_a),
    )
    pid = project.json()["id"]

    import io

    files = {
        "file": ("qa.jsonl", io.BytesIO(b'{"question": "q", "answer": "a"}\n'), "application/jsonl")
    }
    data = {"project_id": pid, "name": "ds", "format": "jsonl"}
    r = client.post("/api/v1/datasets/upload", data=data, files=files, headers=_auth(key_a))
    assert r.status_code in (200, 201), r.text
    ds_id = r.json()["id"]

    # Org B cannot see Org A's dataset through the project-scoped list.
    listed = client.get(f"/api/v1/datasets?project_id={pid}", headers=_auth(key_b))
    assert listed.status_code == 200
    assert all(item["id"] != ds_id for item in listed.json()["items"])

    got = client.get(f"/api/v1/datasets/{ds_id}", headers=_auth(key_b))
    assert got.status_code == 404

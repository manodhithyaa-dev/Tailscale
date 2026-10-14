"""Integration tests driving the FastAPI app in-process.

These require the MySQL console schema to be reachable (the same one the app
uses).  Each test creates uniquely named users and removes them afterwards.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import console_server


@pytest.fixture()
def client():
    with TestClient(console_server.app) as c:
        yield c


def _signup(client, username, password="abcd", role="Viewer", email=None):
    return client.post(
        "/api/auth/signup",
        json={
            "name": "Test User",
            "username": username,
            "email": email or f"{username}@example.com",
            "password": password,
            "role": role,
        },
    )


def test_health(client):
    assert client.get("/api/health").status_code == 200


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/instances").status_code == 401
    assert client.get("/api/files").status_code == 401
    assert client.get("/api/databases").status_code == 401


def test_login_with_bad_credentials_is_generic(client):
    r = client.post(
        "/api/auth/login",
        json={"identifier": "definitely-not-a-user", "password": "whatever"},
    )
    assert r.status_code == 400
    assert "invalid credentials" in r.json()["error"].lower()


def test_signup_password_policy(client, cleanup_user):
    name = f"weak{uuid.uuid4().hex[:8]}"
    r = _signup(client, name, password="abc")
    assert r.status_code == 400
    assert "at least" in r.json()["error"].lower()


def test_signup_rejects_invalid_username(client):
    r = _signup(client, "bad name!")
    assert r.status_code == 400


def test_signup_rejects_invalid_email(client):
    r = _signup(client, f"u{uuid.uuid4().hex[:8]}", email="not-an-email")
    assert r.status_code == 400


def test_signup_never_grants_administrator(client, cleanup_user):
    name = f"esc{uuid.uuid4().hex[:8]}"
    cleanup_user(name)
    r = _signup(client, name, role="Administrator")
    assert r.status_code == 201
    assert r.json()["user"]["role"] == "Viewer"


def test_viewer_can_select_but_not_mutate(client, cleanup_user):
    name = f"view{uuid.uuid4().hex[:8]}"
    cleanup_user(name)
    r = _signup(client, name, role="Viewer")
    assert r.status_code == 201

    ok = client.post("/api/query", json={"query": "SELECT 1 AS n"})
    assert ok.status_code == 200
    assert ok.json()["columns"] == ["n"]

    blocked = client.post("/api/query", json={"query": "DELETE FROM nimbus_users"})
    assert blocked.status_code == 403


def test_viewer_cannot_read_console_metadata(client, cleanup_user):
    name = f"meta{uuid.uuid4().hex[:8]}"
    cleanup_user(name)
    assert _signup(client, name, role="Viewer").status_code == 201

    r = client.post("/api/query", json={"query": "SELECT token FROM nimbus_sessions"})
    assert r.status_code == 403

    r = client.post(
        "/api/query", json={"query": "SELECT * FROM `nimbus_users`"}
    )
    assert r.status_code == 403


def test_viewer_cannot_write_resources(client, cleanup_user):
    name = f"ro{uuid.uuid4().hex[:8]}"
    cleanup_user(name)
    assert _signup(client, name, role="Viewer").status_code == 201
    r = client.post("/api/files/folder", json={"name": "nope"})
    assert r.status_code == 403


def test_folder_name_is_sanitised(client, cleanup_user):
    name = f"dev{uuid.uuid4().hex[:8]}"
    cleanup_user(name)
    assert _signup(client, name, role="Developer").status_code == 201

    r = client.post("/api/files/folder", json={"name": "a/../../etc"})
    assert r.status_code == 201
    assert r.json()["file"]["name"] == "etc"

    r = client.post("/api/files/folder", json={"name": ".."})
    assert r.status_code == 201
    assert r.json()["file"]["name"] == "file"


def test_login_throttle_locks_out_after_failures(client, cleanup_user):
    name = f"lock{uuid.uuid4().hex[:8]}"
    cleanup_user(name)
    assert _signup(client, name, role="Viewer").status_code == 201

    last = None
    for _ in range(8):
        last = client.post(
            "/api/auth/login", json={"identifier": name, "password": "wrong"}
        )
    assert last.status_code == 429

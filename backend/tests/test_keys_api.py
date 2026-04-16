"""Integration tests for /api/v1/keys using in-memory DB stubs."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    import main as m
    import src.auth.dashboard_session as ds
    import src.auth.keys_api as k

    # Override dashboard session to return user_id=1 unconditionally.
    async def fake_session() -> int:
        return 1

    m.app.dependency_overrides[ds.require_dashboard_session] = fake_session

    # In-memory rows + monotonic id.
    rows: list[dict] = []
    counter = {"n": 0}

    async def fake_create_api_key(uid, name, prefix, hidx, sh):
        counter["n"] += 1
        rows.append(
            {
                "id": counter["n"],
                "user_id": uid,
                "name": name,
                "prefix": prefix,
                "hmac_index": hidx,
                "secret_hash": sh,
                "revoked_at": None,
                "created_at": "2026-04-15T00:00:00",
                "last_used_at": None,
            }
        )
        return counter["n"]

    monkeypatch.setattr(k, "create_api_key", fake_create_api_key)

    # Fake async session that intercepts text() queries used by rotate/revoke/list/rename.
    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def first(self):
            return self._rows[0] if self._rows else None

        def all(self):
            return self._rows

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def execute(self, stmt, params=None):
            params = params or {}
            sql = str(stmt)
            # LIST
            if "SELECT id, name, prefix, created_at" in sql:
                out = [
                    (
                        r["id"],
                        r["name"],
                        r["prefix"],
                        r["created_at"],
                        r["last_used_at"],
                        r["revoked_at"],
                    )
                    for r in rows
                    if r["user_id"] == params["u"]
                ]
                return _FakeResult(out)
            # ROTATE (update old, return name)
            if "RETURNING name" in sql and "revoked_at IS NULL" in sql:
                for r in rows:
                    if (
                        r["id"] == params["i"]
                        and r["user_id"] == params["u"]
                        and r["revoked_at"] is None
                    ):
                        r["revoked_at"] = "2026-04-15T00:00:00"
                        return _FakeResult([(r["name"],)])
                return _FakeResult([])
            # REVOKE
            if "RETURNING id" in sql and "revoked_at IS NULL" in sql:
                for r in rows:
                    if (
                        r["id"] == params["i"]
                        and r["user_id"] == params["u"]
                        and r["revoked_at"] is None
                    ):
                        r["revoked_at"] = "2026-04-15T00:00:00"
                        return _FakeResult([(r["id"],)])
                return _FakeResult([])
            # RENAME
            if "SET name = :n" in sql:
                for r in rows:
                    if r["id"] == params["i"] and r["user_id"] == params["u"]:
                        r["name"] = params["n"]
                        return _FakeResult([(r["id"],)])
                return _FakeResult([])
            return _FakeResult([])

        async def commit(self):
            return None

    def fake_session_maker():
        def _factory():
            return _FakeSession()

        return _factory

    monkeypatch.setattr(k, "_session", fake_session_maker)

    yield TestClient(m.app)
    m.app.dependency_overrides.clear()


def test_create_key_returns_prefix_and_sets_reveal_cookie(client):
    r = client.post("/api/v1/keys", json={"name": "CI"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "prefix" in body and len(body["prefix"]) == 8
    sc = r.headers.get("set-cookie", "")
    assert "cv_mint_once=cv_live_" in sc
    assert "Path=/dashboard/keys" in sc
    assert "Max-Age=60" in sc


def test_rotate_atomic(client):
    c = client.post("/api/v1/keys", json={"name": "rotate-me"}).json()
    r = client.post(f"/api/v1/keys/{c['id']}/rotate")
    assert r.status_code == 200, r.text
    new_body = r.json()
    assert new_body["prefix"] != c["prefix"]
    assert new_body["id"] != c["id"]


def test_rotate_missing_returns_404(client):
    r = client.post("/api/v1/keys/9999/rotate")
    assert r.status_code == 404
    assert r.json()["code"] == "key_not_found"


def test_list_keys_returns_created(client):
    client.post("/api/v1/keys", json={"name": "one"})
    client.post("/api/v1/keys", json={"name": "two"})
    r = client.get("/api/v1/keys")
    assert r.status_code == 200
    names = {k["name"] for k in r.json()}
    assert {"one", "two"}.issubset(names)


def test_revoke_then_rotate_404(client):
    c = client.post("/api/v1/keys", json={"name": "x"}).json()
    r = client.delete(f"/api/v1/keys/{c['id']}")
    assert r.status_code == 204
    # Rotating a revoked key should 404.
    r = client.post(f"/api/v1/keys/{c['id']}/rotate")
    assert r.status_code == 404


def test_rename(client):
    c = client.post("/api/v1/keys", json={"name": "old"}).json()
    r = client.patch(f"/api/v1/keys/{c['id']}", json={"name": "new"})
    assert r.status_code == 200
    assert r.json()["name"] == "new"

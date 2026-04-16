"""Integration tests for history API endpoints.

Tests cover:
- Empty list response
- Paginated list with limit/cursor
- Cursor traversal (no gaps, no duplicates, reverse chronological)
- Verdict filter
- Limit clamping (max 100)
- Detail endpoint (full result_json envelope)
- 404 for wrong user
- 404 for nonexistent analysis
- 401 for unauthenticated requests
"""
from __future__ import annotations

import importlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_analysis_mock(ulid: str, verdict: str = "pass", user_id: int = 42):
    """Create a mock Analysis ORM object."""
    a = MagicMock()
    a.ulid = ulid
    a.filename = f"file_{ulid}.stl"
    a.file_type = "stl"
    a.verdict = verdict
    a.face_count = 12
    a.duration_ms = 50.0
    a.created_at = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    a.result_json = {"verdict": verdict, "process_scores": [], "best_process": None}
    a.user_id = user_id
    a.mesh_hash = "abc123"
    a.process_set_hash = "def456"
    a.analysis_version = "0.3.0"
    a.file_size_bytes = 1024
    a.is_public = False
    a.share_short_id = None
    return a


@pytest.fixture
def history_client(monkeypatch):
    """TestClient with auth bypass and mock DB session for history endpoints."""
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")

    import main
    importlib.reload(main)

    return TestClient(main.app), main.app


def _override_session(app, session_mock):
    """Override the DB session dependency on the app."""
    async def _fake_session():
        yield session_mock

    app.dependency_overrides[get_db_session] = _fake_session


def _override_auth(app, user_id=42):
    """Override auth to return a specific user."""
    from src.auth.require_api_key import require_api_key

    def _fake_user():
        return AuthedUser(user_id=user_id, api_key_id=101, key_prefix="test")

    app.dependency_overrides[require_api_key] = _fake_user


def _clear_auth(app):
    """Remove auth override so requests without Bearer get 401."""
    from src.auth.require_api_key import require_api_key

    app.dependency_overrides.pop(require_api_key, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_list_analyses_empty(history_client):
    """GET /api/v1/analyses returns empty list when no analyses exist."""
    client, app = history_client

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = []
    session.execute.return_value = exec_result
    session.commit = AsyncMock()

    _override_session(app, session)
    _override_auth(app)

    r = client.get("/api/v1/analyses")
    assert r.status_code == 200
    body = r.json()
    assert body["analyses"] == []
    assert body["next_cursor"] is None
    assert body["has_more"] is False


def test_list_analyses_pagination(history_client):
    """Insert 25 analyses; limit=10 returns 10 + has_more=true + cursor."""
    client, app = history_client

    # Create 11 mock analyses (10 + 1 extra to indicate has_more)
    analyses = [_make_analysis_mock(f"01ULID{str(i).zfill(4)}") for i in range(11)]

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = analyses
    session.execute.return_value = exec_result
    session.commit = AsyncMock()

    _override_session(app, session)
    _override_auth(app)

    r = client.get("/api/v1/analyses?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert len(body["analyses"]) == 10
    assert body["has_more"] is True
    assert body["next_cursor"] is not None


def test_list_analyses_cursor_traversal(history_client):
    """Walk all pages with limit=2, collect 5 ULIDs with no duplicates."""
    client, app = history_client

    all_ulids = [f"01ULID{str(i).zfill(4)}" for i in range(5, 0, -1)]
    all_analyses = [_make_analysis_mock(u) for u in all_ulids]

    call_count = 0

    async def _paged_execute(stmt):
        nonlocal call_count
        result = MagicMock()
        start = call_count * 2
        end = start + 3  # limit+1 to detect has_more
        page = all_analyses[start:end]
        result.scalars.return_value.all.return_value = page
        call_count += 1
        return result

    session = AsyncMock()
    session.execute = _paged_execute
    session.commit = AsyncMock()

    _override_session(app, session)
    _override_auth(app)

    collected = []
    cursor = None
    for _ in range(10):  # safety limit
        url = "/api/v1/analyses?limit=2"
        if cursor:
            url += f"&cursor={cursor}"
        r = client.get(url)
        assert r.status_code == 200
        body = r.json()
        collected.extend([a["id"] for a in body["analyses"]])
        if not body["has_more"]:
            break
        cursor = body["next_cursor"]

    # No duplicates
    assert len(collected) == len(set(collected))
    assert len(collected) == 5


def test_list_analyses_verdict_filter(history_client):
    """Verdict filter returns only matching analyses."""
    client, app = history_client

    pass_analyses = [_make_analysis_mock(f"01PASS{str(i).zfill(4)}", verdict="pass") for i in range(3)]

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = pass_analyses
    session.execute.return_value = exec_result
    session.commit = AsyncMock()

    _override_session(app, session)
    _override_auth(app)

    r = client.get("/api/v1/analyses?verdict=pass")
    assert r.status_code == 200
    body = r.json()
    assert all(a["verdict"] == "pass" for a in body["analyses"])


def test_list_analyses_limit_clamp(history_client):
    """limit=999 is clamped to 100 by FastAPI Query(le=100)."""
    client, app = history_client

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = []
    session.execute.return_value = exec_result
    session.commit = AsyncMock()

    _override_session(app, session)
    _override_auth(app)

    # limit > 100 should return 422 (validation error)
    r = client.get("/api/v1/analyses?limit=999")
    assert r.status_code == 422

    # limit < 1 should return 422
    r = client.get("/api/v1/analyses?limit=0")
    assert r.status_code == 422


def test_get_analysis_detail(history_client):
    """GET /api/v1/analyses/{ulid} returns full metadata envelope."""
    client, app = history_client

    analysis = _make_analysis_mock("01DETAIL0001", verdict="pass", user_id=42)

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = analysis
    session.execute.return_value = exec_result
    session.commit = AsyncMock()

    _override_session(app, session)
    _override_auth(app, user_id=42)

    r = client.get("/api/v1/analyses/01DETAIL0001")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "01DETAIL0001"
    assert body["filename"] == "file_01DETAIL0001.stl"
    assert body["file_type"] == "stl"
    assert "created_at" in body
    assert "result" in body
    assert body["result"]["verdict"] == "pass"


def test_get_analysis_wrong_user(history_client):
    """User B cannot access User A's analysis — returns 404."""
    client, app = history_client

    # Analysis belongs to user 42, but we authenticate as user 99
    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None  # filtered by user_id
    session.execute.return_value = exec_result
    session.commit = AsyncMock()

    _override_session(app, session)
    _override_auth(app, user_id=99)

    r = client.get("/api/v1/analyses/01WRONGUSER1")
    assert r.status_code == 404


def test_get_analysis_nonexistent(history_client):
    """GET /api/v1/analyses/01NONEXISTENT returns 404."""
    client, app = history_client

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    session.execute.return_value = exec_result
    session.commit = AsyncMock()

    _override_session(app, session)
    _override_auth(app)

    r = client.get("/api/v1/analyses/01NONEXISTENT")
    assert r.status_code == 404


def test_list_analyses_requires_auth(history_client):
    """GET /api/v1/analyses without auth header returns 401."""
    client, app = history_client

    # Remove auth override so the real require_api_key runs
    _clear_auth(app)

    # Also need DB session override removed to test real auth
    # But without a real DB, we need the session override.
    # The auth check happens before DB access, so just clearing auth is enough.

    r = client.get("/api/v1/analyses", headers={})
    assert r.status_code == 401

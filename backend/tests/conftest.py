"""Shared pytest fixtures for CADVerify.

All fixtures generate meshes *procedurally* via trimesh.creation so nothing
binary has to be checked into git. Any fixture whose construction needs
boolean operations (difference / union) is skipped gracefully if the
underlying CSG backend (manifold3d) is missing — the rest of the suite
still runs.
"""

from __future__ import annotations

import base64
import io
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import trimesh

from src.auth.require_api_key import AuthedUser


# ──────────────────────────────────────────────────────────────
# DB test fixtures — mocked async sessions for Phase 3 tests
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def test_db_url():
    """Return test database URL (or fall back to DATABASE_URL)."""
    return os.environ.get(
        "TEST_DATABASE_URL", os.environ.get("DATABASE_URL", "sqlite+aiosqlite://")
    )


@pytest.fixture
def async_engine(test_db_url):
    """Return a mock async engine (no live DB required)."""
    engine = AsyncMock()
    engine.url = test_db_url
    return engine


@pytest.fixture
def db_session():
    """Function-scoped mock async session with rollback semantics.

    Provides a realistic AsyncSession mock that tracks added objects and
    supports execute/flush/rollback/commit for unit tests without a real DB.
    """
    session = AsyncMock()
    session._added = []

    original_add = session.add

    def _track_add(obj):
        session._added.append(obj)

    session.add = _track_add

    async def _fake_flush():
        # Assign fake IDs to added objects that lack one
        for i, obj in enumerate(session._added, start=1):
            if hasattr(obj, "id") and obj.id is None:
                obj.id = i

    session.flush = _fake_flush

    async def _fake_rollback():
        pass

    session.rollback = _fake_rollback

    async def _fake_commit():
        pass

    session.commit = _fake_commit

    # Default execute returns empty result (no cache hit)
    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = None
    exec_result.scalars.return_value.all.return_value = []
    exec_result.scalar_one_or_none.return_value = None
    session.execute.return_value = exec_result

    return session


@pytest.fixture
def test_user():
    """Return a test user ID (no real DB row needed for mock tests)."""
    return 42


@pytest.fixture
def test_api_key():
    """Return a test API key ID."""
    return 101


@pytest.fixture
def authed_user(test_user, test_api_key):
    """Return an AuthedUser instance for the test user."""
    return AuthedUser(user_id=test_user, api_key_id=test_api_key, key_prefix="test_pfx")


# ──────────────────────────────────────────────────────────────
# Auth env — autouse so every test sees valid pepper/secrets
# ──────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    monkeypatch.setenv("API_KEY_PEPPER", base64.b64encode(b"a" * 32).decode())
    monkeypatch.setenv("MAGIC_LINK_SECRET", base64.b64encode(b"b" * 32).decode())
    monkeypatch.setenv(
        "DASHBOARD_SESSION_SECRET", base64.b64encode(b"c" * 32).decode()
    )
    monkeypatch.setenv("TURNSTILE_SECRET", "test")
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://cadverify.com")
    monkeypatch.setenv("SESSION_SECRET", "dev")
    # Reset hashing pepper cache so each test gets fresh config.
    try:
        import src.auth.hashing as _h

        _h._PEPPER = None
    except Exception:
        pass
    yield


def _apply_auth_bypass(app) -> None:
    """Install dependency overrides so tests can call /api/v1/* w/o Bearer
    and without a real database connection.

    Used by 02.C: existing end-to-end tests (test_api, test_rule_packs,
    test_frontend_errors, test_step_corruption, test_large_mesh) were written
    before require_api_key existed. Rather than sprinkle Bearer headers + DB
    mocks through every test, we bypass the dependency globally on the main
    app instance. Tests that need to exercise the real auth enforcement build
    their own isolated FastAPI apps (see test_require_api_key, test_rate_limit).
    """
    from unittest.mock import AsyncMock, MagicMock

    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    def _fake_user():
        return AuthedUser(user_id=1, api_key_id=1, key_prefix="testkey1")

    async def _fake_db_session():
        """Yield a mock async session that no-ops on ORM calls.

        The mock is transparent enough for analysis_service to call
        session.execute / session.add / session.flush without hitting a real
        DB, while still allowing the pipeline result to pass through.
        """
        session = AsyncMock()
        # _check_cache returns None (always cache miss) so the full pipeline runs
        exec_result = MagicMock()
        exec_result.scalars.return_value.first.return_value = None
        session.execute.return_value = exec_result
        # flush after _persist_analysis — give the Analysis object a fake id
        async def _fake_flush():
            pass
        session.flush = _fake_flush
        yield session

    app.dependency_overrides[require_api_key] = _fake_user
    app.dependency_overrides[get_db_session] = _fake_db_session


@pytest.fixture(autouse=True)
def _bypass_api_key_auth(monkeypatch):
    """Re-apply the auth bypass whenever a test reloads `main` and creates
    a new FastAPI app instance.

    We wrap `importlib.reload` so that any call to reload(main) installs the
    override on the fresh app before the test constructs a TestClient.
    """
    import importlib

    _orig_reload = importlib.reload

    def _reload_and_bypass(mod):
        result = _orig_reload(mod)
        try:
            if getattr(result, "__name__", "") == "main":
                _apply_auth_bypass(result.app)
        except Exception:
            pass
        return result

    monkeypatch.setattr(importlib, "reload", _reload_and_bypass)

    # Also apply to any already-imported main (covers tests that don't reload).
    try:
        import sys

        if "main" in sys.modules:
            _apply_auth_bypass(sys.modules["main"].app)
    except Exception:
        pass

    yield

    try:
        import sys

        if "main" in sys.modules:
            from src.auth.require_api_key import require_api_key
            from src.db.engine import get_db_session

            sys.modules["main"].app.dependency_overrides.pop(
                require_api_key, None
            )
            sys.modules["main"].app.dependency_overrides.pop(
                get_db_session, None
            )
    except Exception:
        pass


def _try_csg(op):
    """Run a boolean-op closure, skip the test if the backend is missing."""
    try:
        return op()
    except Exception as e:
        pytest.skip(f"boolean ops unavailable: {e}")


# ──────────────────────────────────────────────────────────────
# Primitive meshes
# ──────────────────────────────────────────────────────────────
@pytest.fixture
def cube_10mm() -> trimesh.Trimesh:
    """Watertight 10mm cube — the universal 'it should just pass' fixture."""
    return trimesh.creation.box(extents=[10.0, 10.0, 10.0])


@pytest.fixture
def plate_thin_2mm() -> trimesh.Trimesh:
    """30×30×2 mm plate — exercises wall-thickness detection at the low end."""
    return trimesh.creation.box(extents=[30.0, 30.0, 2.0])


@pytest.fixture
def plate_thin_04mm() -> trimesh.Trimesh:
    """30×30×0.4 mm plate — sub-mm wall, should fail FDM (0.8mm min)."""
    return trimesh.creation.box(extents=[30.0, 30.0, 0.4])


@pytest.fixture
def cylinder_50h_10r() -> trimesh.Trimesh:
    """Solid cylinder, 20mm diameter × 50mm tall."""
    return trimesh.creation.cylinder(radius=10.0, height=50.0, sections=64)


@pytest.fixture
def plate_with_hole(cube_10mm) -> trimesh.Trimesh:
    """50×50×10 plate with a 5mm-radius hole through it."""
    def build():
        plate = trimesh.creation.box(extents=[50.0, 50.0, 10.0])
        drill = trimesh.creation.cylinder(radius=5.0, height=12.0, sections=64)
        return plate.difference(drill)
    return _try_csg(build)


@pytest.fixture
def hollow_box_02mm_wall() -> trimesh.Trimesh:
    """20mm cube with 19.6mm inner cavity → 0.2mm walls."""
    def build():
        outer = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
        inner = trimesh.creation.box(extents=[19.6, 19.6, 19.6])
        return outer.difference(inner)
    return _try_csg(build)


@pytest.fixture
def non_watertight_box() -> trimesh.Trimesh:
    """10mm cube with one face torn off so universal checks fail."""
    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    return trimesh.Trimesh(
        vertices=mesh.vertices,
        faces=mesh.faces[:-2],
        process=False,
    )


# ──────────────────────────────────────────────────────────────
# Serialization helpers
# ──────────────────────────────────────────────────────────────
@pytest.fixture
def stl_bytes_of():
    """Return a callable that serializes a mesh to binary STL bytes."""
    def _serialize(mesh: trimesh.Trimesh) -> bytes:
        buf = io.BytesIO()
        mesh.export(buf, file_type="stl")
        return buf.getvalue()
    return _serialize

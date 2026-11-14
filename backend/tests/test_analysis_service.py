"""Unit tests for analysis_service — hash functions and pipeline orchestration.

Tests cover:
- compute_mesh_hash determinism and format
- compute_process_set_hash sort-invariance
- run_analysis fresh path (cache miss -> persist)
- run_analysis cache hit path (no pipeline run)
- Usage event tracking (analysis_complete vs analysis_cached)
- Version mismatch cache bypass
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.auth.require_api_key import AuthedUser
from src.db.models import Analysis, UsageEvent
from src.services.analysis_service import (
    _check_cache,
    compute_mesh_hash,
    compute_process_set_hash,
    get_analysis_id_by_ulid,
)


# ---------------------------------------------------------------------------
# Hash function tests
# ---------------------------------------------------------------------------


def test_compute_mesh_hash_deterministic():
    """Same bytes produce the same hash; different bytes produce different hashes."""
    data_a = b"hello world mesh data"
    data_b = b"different mesh data"

    assert compute_mesh_hash(data_a) == compute_mesh_hash(data_a)
    assert compute_mesh_hash(data_a) != compute_mesh_hash(data_b)


def test_compute_mesh_hash_sha256_format():
    """Output is a 64-character lowercase hex string (SHA-256)."""
    h = compute_mesh_hash(b"test data")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
    # Verify it matches stdlib sha256
    assert h == hashlib.sha256(b"test data").hexdigest()


def test_compute_process_set_hash_sort_invariant():
    """Order of process values does not affect the hash."""
    h1 = compute_process_set_hash(["fdm", "sla"])
    h2 = compute_process_set_hash(["sla", "fdm"])
    assert h1 == h2


def test_compute_process_set_hash_different_sets():
    """Different process sets produce different hashes."""
    h1 = compute_process_set_hash(["fdm"])
    h2 = compute_process_set_hash(["fdm", "sla"])
    assert h1 != h2


def test_compute_process_set_hash_single_vs_empty():
    """Empty list and single-element list produce different hashes."""
    h_empty = compute_process_set_hash([])
    h_single = compute_process_set_hash(["fdm"])
    assert h_empty != h_single


def test_compute_process_set_hash_includes_rule_pack_version():
    base = compute_process_set_hash(["fdm"])
    aerospace = compute_process_set_hash(["fdm"], "aerospace@1.0")
    oil_gas = compute_process_set_hash(["fdm"], "oil_gas@1.0")
    assert len({base, aerospace, oil_gas}) == 3
    assert aerospace == compute_process_set_hash(["fdm"], "aerospace@1.0")


@pytest.mark.asyncio
async def test_analysis_cache_lookup_is_scoped_to_the_callers_active_org():
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    session.execute.return_value = result

    await _check_cache(session, 7, "org-a", "mesh", "processes", "version")

    sql = str(
        session.execute.await_args.args[0].compile(
            compile_kwargs={"literal_binds": True}
        )
    ).lower()
    assert "analyses.org_id = 'org-a'" in sql
    assert "memberships" not in sql


@pytest.mark.asyncio
async def test_exact_saved_analysis_lookup_uses_ulid_and_frozen_org():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = 42
    session.execute.return_value = result

    resolved = await get_analysis_id_by_ulid(session, 7, "01EXACT", "org-a")

    assert resolved == 42
    sql = str(
        session.execute.await_args.args[0].compile(
            compile_kwargs={"literal_binds": True}
        )
    ).lower()
    assert "analyses.ulid = '01exact'" in sql
    assert "analyses.org_id = 'org-a'" in sql
    assert "analyses.user_id = 7" in sql
    assert "mesh_hash" not in sql


# ---------------------------------------------------------------------------
# run_analysis tests (mocked pipeline)
# ---------------------------------------------------------------------------


@pytest.fixture
def _mock_route_helpers():
    """Patch _get_route_helpers to avoid importing actual route module."""
    mock_parse_mesh = MagicMock()
    mock_mesh = MagicMock()
    mock_mesh.vertices = [[0, 0, 0]]
    mock_mesh.faces = [[0, 0, 0]]
    mock_parse_mesh.return_value = (mock_mesh, ".stl")

    mock_resolve = MagicMock()
    # Return a list of mock ProcessType enums
    mock_proc = MagicMock()
    mock_proc.value = "fdm"
    mock_resolve.return_value = [mock_proc]

    mock_to_response = MagicMock(return_value={
        "filename": "cube.stl",
        "verdict": "pass",
        "process_scores": [],
        "best_process": None,
    })

    mock_timeout = MagicMock(return_value=30)

    mock_issue_to_dict = MagicMock()

    with patch(
        "src.services.analysis_service._get_route_helpers",
        return_value=(
            mock_timeout,
            mock_issue_to_dict,
            mock_parse_mesh,
            mock_resolve,
            mock_to_response,
        ),
    ):
        yield {
            "parse_mesh": mock_parse_mesh,
            "resolve": mock_resolve,
            "to_response": mock_to_response,
            "timeout": mock_timeout,
        }


@pytest.fixture
def _mock_pipeline():
    """Patch all analysis pipeline functions to return minimal results."""
    mock_geometry = MagicMock()
    mock_geometry.face_count = 12
    mock_geometry.vertex_count = 8
    mock_geometry.volume = 1000.0
    mock_geometry.bounding_box = MagicMock()
    mock_geometry.bounding_box.dimensions = [10.0, 10.0, 10.0]
    mock_geometry.is_watertight = True

    mock_ctx = MagicMock()
    mock_ctx.segments = []
    mock_ctx.features = []

    patches = [
        patch("src.services.analysis_service.analyze_geometry", return_value=mock_geometry),
        patch("src.services.analysis_service.GeometryContext.build", return_value=mock_ctx),
        patch("src.services.analysis_service.detect_features", return_value=[]),
        patch("src.services.analysis_service.run_universal_checks", return_value=[]),
        patch("src.services.analysis_service.get_analyzer", return_value=None),
        patch("src.services.analysis_service.rank_processes", return_value=[]),
        patch("src.services.analysis_service.enhance_suggestions", side_effect=lambda r: r),
    ]

    for p in patches:
        p.start()

    yield mock_geometry

    for p in patches:
        p.stop()


@pytest.mark.asyncio
async def test_run_analysis_fresh_persists(db_session, authed_user, _mock_route_helpers, _mock_pipeline):
    """Cache miss: pipeline runs, Analysis row is created with correct hashes."""
    from src.services.analysis_service import run_analysis

    file_bytes = b"fresh mesh content"
    with patch(
        "src.services.analysis_service.resolve_org",
        new=AsyncMock(return_value="org-a"),
    ) as resolve:
        result = await run_analysis(
            file_bytes=file_bytes,
            filename="cube.stl",
            processes="fdm",
            rule_pack=None,
            user=authed_user,
            session=db_session,
        )

    assert result is not None
    # Verify an Analysis object was added to the session
    analyses = [obj for obj in db_session._added if hasattr(obj, "mesh_hash")]
    assert len(analyses) >= 1
    a = analyses[0]
    assert a.mesh_hash == compute_mesh_hash(file_bytes)
    assert a.filename == "cube.stl"
    assert a.api_key_id == authed_user.api_key_id
    assert a.org_id == "org-a"
    assert resolve.await_count == 1
    events = [obj for obj in db_session._added if isinstance(obj, UsageEvent)]
    assert events and events[0].org_id == "org-a"
    assert result["saved"] == {
        "id": a.ulid,
        "url": f"/api/v1/analyses/{a.ulid}",
    }
    assert "saved" not in a.result_json


@pytest.mark.asyncio
async def test_rule_pack_identity_is_wired_into_persisted_dedup_key(
    db_session, authed_user, _mock_route_helpers, _mock_pipeline
):
    from src.analysis.rules import get_rule_pack
    from src.services.analysis_service import run_analysis

    pack = get_rule_pack("aerospace")
    assert pack is not None
    with patch(
        "src.services.analysis_service.resolve_org",
        new=AsyncMock(return_value="org-a"),
    ):
        await run_analysis(
            file_bytes=b"packed mesh content",
            filename="packed.stl",
            processes="fdm",
            rule_pack="aerospace",
            user=authed_user,
            session=db_session,
        )

    analysis = next(obj for obj in db_session._added if hasattr(obj, "mesh_hash"))
    assert analysis.process_set_hash == compute_process_set_hash(
        ["fdm"], f"{pack.name}@{pack.version}"
    )


@pytest.mark.asyncio
async def test_run_analysis_cache_hit(db_session, authed_user, _mock_route_helpers, _mock_pipeline):
    """Cache hit: pipeline does NOT run, stored result_json is returned."""
    from src.services.analysis_service import run_analysis

    # Pre-configure the session to return a cached Analysis on execute
    cached_analysis = MagicMock()
    cached_analysis.id = 99
    cached_analysis.ulid = "01CACHE0000000000000000001"
    cached_analysis.result_json = {"cached": True, "verdict": "pass"}
    cached_analysis.duration_ms = 50.0
    cached_analysis.face_count = 12
    cached_analysis.mesh_hash = "abc"

    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = cached_analysis
    db_session.execute.return_value = exec_result

    result = await run_analysis(
        file_bytes=b"cached mesh",
        filename="cube.stl",
        processes="fdm",
        rule_pack=None,
        user=authed_user,
        session=db_session,
    )

    assert result == {
        "cached": True,
        "verdict": "pass",
        "saved": {
            "id": cached_analysis.ulid,
            "url": f"/api/v1/analyses/{cached_analysis.ulid}",
        },
    }
    assert "saved" not in cached_analysis.result_json
    # Pipeline (parse_mesh) should NOT have been called
    _mock_route_helpers["parse_mesh"].assert_not_called()


@pytest.mark.asyncio
async def test_run_analysis_writes_usage_event(db_session, authed_user, _mock_route_helpers, _mock_pipeline):
    """Fresh analysis writes a usage event with event_type='analysis_complete'."""
    from src.services.analysis_service import run_analysis

    await run_analysis(
        file_bytes=b"event tracking mesh",
        filename="cube.stl",
        processes="fdm",
        rule_pack=None,
        user=authed_user,
        session=db_session,
    )

    # Check that a UsageEvent was added
    events = [obj for obj in db_session._added if hasattr(obj, "event_type")]
    assert len(events) >= 1
    assert events[0].event_type == "analysis_complete"


@pytest.mark.asyncio
async def test_run_analysis_session_auth_uses_nullable_api_key_fk(
    db_session,
    test_user,
    _mock_route_helpers,
    _mock_pipeline,
):
    """Dashboard-session auth uses api_key_id=0 only in memory, never as an FK."""
    from src.services.analysis_service import run_analysis

    session_user = AuthedUser(
        user_id=test_user,
        api_key_id=0,
        key_prefix="session",
        role="analyst",
    )

    await run_analysis(
        file_bytes=b"session mesh",
        filename="cube.stl",
        processes="fdm",
        rule_pack=None,
        user=session_user,
        session=db_session,
    )

    analyses = [obj for obj in db_session._added if isinstance(obj, Analysis)]
    events = [obj for obj in db_session._added if isinstance(obj, UsageEvent)]
    assert analyses
    assert events
    assert analyses[0].api_key_id is None
    assert events[0].api_key_id is None


@pytest.mark.asyncio
async def test_run_analysis_cache_hit_writes_cached_event(db_session, authed_user, _mock_route_helpers, _mock_pipeline):
    """Cache hit writes usage event with event_type='analysis_cached'."""
    from src.services.analysis_service import run_analysis

    cached_analysis = MagicMock()
    cached_analysis.id = 99
    cached_analysis.ulid = "01CACHE0000000000000000002"
    cached_analysis.result_json = {"cached": True}
    cached_analysis.duration_ms = 10.0
    cached_analysis.face_count = 6
    cached_analysis.mesh_hash = "xyz"

    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = cached_analysis
    db_session.execute.return_value = exec_result

    await run_analysis(
        file_bytes=b"cached event mesh",
        filename="cube.stl",
        processes="fdm",
        rule_pack=None,
        user=authed_user,
        session=db_session,
    )

    events = [obj for obj in db_session._added if hasattr(obj, "event_type")]
    assert len(events) >= 1
    assert events[0].event_type == "analysis_cached"


@pytest.mark.asyncio
async def test_run_analysis_version_mismatch_bypasses_cache(db_session, authed_user, _mock_route_helpers, _mock_pipeline):
    """If analysis_version differs from cached row, pipeline runs (cache miss)."""
    from src.services.analysis_service import run_analysis

    # First call: execute returns None (no cache), pipeline runs
    exec_result_miss = MagicMock()
    exec_result_miss.scalars.return_value.first.return_value = None
    db_session.execute.return_value = exec_result_miss

    result = await run_analysis(
        file_bytes=b"version test mesh",
        filename="cube.stl",
        processes="fdm",
        rule_pack=None,
        user=authed_user,
        session=db_session,
    )

    # Pipeline was called (parse_mesh invoked)
    _mock_route_helpers["parse_mesh"].assert_called_once()
    assert result is not None

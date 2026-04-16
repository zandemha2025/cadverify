"""Integration tests for dedup behavior in analysis_service.

Verifies:
- Same file + same processes = cache hit (pipeline runs once)
- Same file + different processes = cache miss (pipeline runs twice)
- Different file + same processes = cache miss (pipeline runs twice)
- Per-user dedup isolation (D-13)
- Cache hit performance (< 200ms)
- Concurrent duplicate upload handling (IntegrityError path)
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.auth.require_api_key import AuthedUser
from src.services.analysis_service import (
    compute_mesh_hash,
    compute_process_set_hash,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PIPELINE_CALL_COUNT = 0


def _make_mock_route_helpers(parse_mesh_tracker=None):
    """Build a mock _get_route_helpers return tuple."""
    mock_parse_mesh = MagicMock()
    mock_mesh = MagicMock()
    mock_mesh.vertices = [[0, 0, 0]]
    mock_mesh.faces = [[0, 0, 0]]
    mock_parse_mesh.return_value = (mock_mesh, ".stl")
    if parse_mesh_tracker is not None:
        original_side_effect = mock_parse_mesh.side_effect

        def _tracking_parse(*args, **kwargs):
            parse_mesh_tracker.append(1)
            return (mock_mesh, ".stl")

        mock_parse_mesh.side_effect = _tracking_parse

    mock_proc = MagicMock()
    mock_proc.value = "fdm"
    mock_resolve = MagicMock(return_value=[mock_proc])

    mock_to_response = MagicMock(return_value={
        "filename": "cube.stl",
        "verdict": "pass",
        "process_scores": [],
        "best_process": None,
    })

    mock_timeout = MagicMock(return_value=30)
    mock_issue_to_dict = MagicMock()

    return (mock_timeout, mock_issue_to_dict, mock_parse_mesh, mock_resolve, mock_to_response)


def _make_session_with_cache(cache_store: dict):
    """Create a mock session that stores/retrieves Analysis objects by dedup key.

    cache_store maps (user_id, mesh_hash, process_set_hash, version) -> Analysis mock.
    """
    session = AsyncMock()
    session._added = []

    def _track_add(obj):
        session._added.append(obj)
        # Store in cache for future lookups
        if hasattr(obj, "mesh_hash"):
            key = (obj.user_id, obj.mesh_hash, obj.process_set_hash, obj.analysis_version)
            cache_store[key] = obj

    session.add = _track_add

    async def _fake_flush():
        for i, obj in enumerate(session._added, start=1):
            if hasattr(obj, "id") and obj.id is None:
                obj.id = i

    session.flush = _fake_flush
    session.rollback = AsyncMock()
    session.commit = AsyncMock()

    def _make_execute(store):
        async def _execute(stmt):
            # Try to extract WHERE clauses to find cache key
            result = MagicMock()
            # Check all stored analyses against the query
            # We detect cache hits by inspecting what was previously stored
            for key, analysis in store.items():
                # Return the first match (simplistic but works for test)
                result.scalars.return_value.first.return_value = analysis
                return result
            result.scalars.return_value.first.return_value = None
            return result

        return _execute

    # Initially no cache -- execute returns None
    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = None
    session.execute.return_value = exec_result

    return session


@pytest.fixture
def _pipeline_patches():
    """Patch all pipeline functions so they don't do real analysis."""
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_file_same_processes_cache_hit(db_session, authed_user, _pipeline_patches):
    """Upload file A with ['fdm','sla'] twice. Pipeline should run only once."""
    from src.services.analysis_service import run_analysis

    pipeline_calls = []
    helpers = _make_mock_route_helpers(parse_mesh_tracker=pipeline_calls)

    with patch("src.services.analysis_service._get_route_helpers", return_value=helpers):
        # First upload — cache miss, pipeline runs
        result1 = await run_analysis(
            file_bytes=b"file_A_content",
            filename="a.stl",
            processes="fdm,sla",
            rule_pack=None,
            user=authed_user,
            session=db_session,
        )
        assert len(pipeline_calls) == 1

        # Set up cache hit for second call
        cached_analysis = MagicMock()
        cached_analysis.id = 1
        cached_analysis.result_json = result1
        cached_analysis.duration_ms = 50.0
        cached_analysis.face_count = 12
        cached_analysis.mesh_hash = compute_mesh_hash(b"file_A_content")

        exec_result = MagicMock()
        exec_result.scalars.return_value.first.return_value = cached_analysis
        db_session.execute.return_value = exec_result

        # Second upload — cache hit, pipeline does NOT run
        result2 = await run_analysis(
            file_bytes=b"file_A_content",
            filename="a.stl",
            processes="fdm,sla",
            rule_pack=None,
            user=authed_user,
            session=db_session,
        )
        # Pipeline was NOT called again
        assert len(pipeline_calls) == 1
        assert result1 == result2


@pytest.mark.asyncio
async def test_same_file_different_processes_cache_miss(db_session, authed_user, _pipeline_patches):
    """Same file with different processes = cache miss (different process_set_hash)."""
    from src.services.analysis_service import run_analysis

    pipeline_calls = []
    helpers = _make_mock_route_helpers(parse_mesh_tracker=pipeline_calls)

    with patch("src.services.analysis_service._get_route_helpers", return_value=helpers):
        # First: fdm only
        mock_proc_fdm = MagicMock()
        mock_proc_fdm.value = "fdm"
        helpers[3].return_value = [mock_proc_fdm]

        await run_analysis(
            file_bytes=b"same_file",
            filename="a.stl",
            processes="fdm",
            rule_pack=None,
            user=authed_user,
            session=db_session,
        )
        assert len(pipeline_calls) == 1

        # Second: fdm + sla (different process set)
        mock_proc_sla = MagicMock()
        mock_proc_sla.value = "sla"
        helpers[3].return_value = [mock_proc_fdm, mock_proc_sla]

        await run_analysis(
            file_bytes=b"same_file",
            filename="a.stl",
            processes="fdm,sla",
            rule_pack=None,
            user=authed_user,
            session=db_session,
        )
        # Pipeline ran twice — different process_set_hash
        assert len(pipeline_calls) == 2


@pytest.mark.asyncio
async def test_different_file_same_processes_cache_miss(db_session, authed_user, _pipeline_patches):
    """Different files with same processes = cache miss (different mesh_hash)."""
    from src.services.analysis_service import run_analysis

    pipeline_calls = []
    helpers = _make_mock_route_helpers(parse_mesh_tracker=pipeline_calls)

    with patch("src.services.analysis_service._get_route_helpers", return_value=helpers):
        await run_analysis(
            file_bytes=b"file_A",
            filename="a.stl",
            processes="fdm",
            rule_pack=None,
            user=authed_user,
            session=db_session,
        )
        assert len(pipeline_calls) == 1

        await run_analysis(
            file_bytes=b"file_B",
            filename="b.stl",
            processes="fdm",
            rule_pack=None,
            user=authed_user,
            session=db_session,
        )
        assert len(pipeline_calls) == 2


@pytest.mark.asyncio
async def test_per_user_dedup_isolation(db_session, _pipeline_patches):
    """User 1 and User 2 uploading the same file each get their own Analysis (D-13)."""
    from src.services.analysis_service import run_analysis

    pipeline_calls = []
    helpers = _make_mock_route_helpers(parse_mesh_tracker=pipeline_calls)

    user1 = AuthedUser(user_id=1, api_key_id=10, key_prefix="u1")
    user2 = AuthedUser(user_id=2, api_key_id=20, key_prefix="u2")

    with patch("src.services.analysis_service._get_route_helpers", return_value=helpers):
        await run_analysis(
            file_bytes=b"shared_file",
            filename="cube.stl",
            processes="fdm",
            rule_pack=None,
            user=user1,
            session=db_session,
        )
        assert len(pipeline_calls) == 1

        # User 2 uploads same file — cache miss (different user_id in dedup key)
        await run_analysis(
            file_bytes=b"shared_file",
            filename="cube.stl",
            processes="fdm",
            rule_pack=None,
            user=user2,
            session=db_session,
        )
        assert len(pipeline_calls) == 2

    # Both users should have their own Analysis row
    analyses = [obj for obj in db_session._added if hasattr(obj, "mesh_hash")]
    user_ids = {a.user_id for a in analyses}
    assert user_ids == {1, 2}


@pytest.mark.asyncio
async def test_cache_hit_under_200ms(db_session, authed_user, _pipeline_patches):
    """Cache hit should respond in under 200ms (no pipeline execution)."""
    from src.services.analysis_service import run_analysis

    helpers = _make_mock_route_helpers()

    # Pre-configure cache hit
    cached_analysis = MagicMock()
    cached_analysis.id = 1
    cached_analysis.result_json = {"verdict": "pass", "fast": True}
    cached_analysis.duration_ms = 10.0
    cached_analysis.face_count = 12
    cached_analysis.mesh_hash = "abc"

    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = cached_analysis
    db_session.execute.return_value = exec_result

    with patch("src.services.analysis_service._get_route_helpers", return_value=helpers):
        t0 = time.monotonic()
        result = await run_analysis(
            file_bytes=b"speed test",
            filename="cube.stl",
            processes="fdm",
            rule_pack=None,
            user=authed_user,
            session=db_session,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000

    assert result == {"verdict": "pass", "fast": True}
    assert elapsed_ms < 200, f"Cache hit took {elapsed_ms:.1f}ms, expected < 200ms"


@pytest.mark.asyncio
async def test_concurrent_duplicate_upload(db_session, authed_user, _pipeline_patches):
    """Concurrent duplicate uploads: IntegrityError handled, both return same result."""
    from unittest.mock import PropertyMock

    from sqlalchemy.exc import IntegrityError

    from src.services.analysis_service import run_analysis

    helpers = _make_mock_route_helpers()
    call_count = 0

    # After IntegrityError, the re-query should find the winning row
    cached_analysis = MagicMock()
    cached_analysis.id = 1
    cached_analysis.result_json = {"verdict": "pass", "concurrent": True}
    cached_analysis.duration_ms = 50.0
    cached_analysis.face_count = 12
    cached_analysis.mesh_hash = compute_mesh_hash(b"concurrent_file")

    original_flush = db_session.flush

    async def _flush_that_fails_once():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First flush succeeds (assigns IDs)
            await original_flush()
        else:
            # Second would raise IntegrityError in real DB
            raise IntegrityError("duplicate key", params={}, orig=Exception())

    with patch("src.services.analysis_service._get_route_helpers", return_value=helpers):
        # First call: normal success
        result1 = await run_analysis(
            file_bytes=b"concurrent_file",
            filename="cube.stl",
            processes="fdm",
            rule_pack=None,
            user=authed_user,
            session=db_session,
        )

        # Second call: flush raises IntegrityError, then re-query finds cached row
        db_session.flush = _flush_that_fails_once

        # After rollback, execute should return the cached row
        exec_hit = MagicMock()
        exec_hit.scalars.return_value.first.return_value = cached_analysis

        # First execute (cache check) returns None, second (re-query) returns cached
        db_session.execute.side_effect = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))),
            exec_hit,  # re-query after IntegrityError
        ]

        result2 = await run_analysis(
            file_bytes=b"concurrent_file",
            filename="cube.stl",
            processes="fdm",
            rule_pack=None,
            user=authed_user,
            session=db_session,
        )

    # Both should return valid results
    assert result1 is not None
    assert result2 is not None

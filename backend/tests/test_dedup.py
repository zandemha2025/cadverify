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
    AnalysisRun,
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
    # run_analysis / run_quick_analysis now parse via the ASYNC pooled front door
    # (gauntlet F1 fix — off the event loop), so the tracker lives on the awaited
    # helper, which is the one actually invoked on a cache miss.
    mock_parse_mesh_async = AsyncMock(return_value=(mock_mesh, ".stl"))
    if parse_mesh_tracker is not None:
        def _tracking_parse(*args, **kwargs):
            parse_mesh_tracker.append(1)
            return (mock_mesh, ".stl")

        mock_parse_mesh.side_effect = _tracking_parse
        mock_parse_mesh_async.side_effect = _tracking_parse

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

    return (
        mock_timeout,
        mock_issue_to_dict,
        mock_parse_mesh,
        mock_resolve,
        mock_to_response,
        mock_parse_mesh_async,
    )


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
async def test_rule_pack_name_and_version_are_part_of_cache_identity(authed_user):
    """Same bytes/processes under two governed packs must never share a cache row."""
    from src.services.analysis_service import run_analysis

    helpers = _make_mock_route_helpers()
    cached = MagicMock(
        id=9,
        result_json={"verdict": "pass"},
        duration_ms=1.0,
        face_count=12,
    )
    session = AsyncMock()

    with (
        patch("src.services.analysis_service._get_route_helpers", return_value=helpers),
        patch(
            "src.services.analysis_service._check_cache",
            new=AsyncMock(return_value=cached),
        ) as check_cache,
        patch(
            "src.services.analysis_service._write_usage_event",
            new=AsyncMock(),
        ),
    ):
        await run_analysis(
            b"same",
            "same.stl",
            "fdm",
            "aerospace",
            authed_user,
            session,
        )
        await run_analysis(
            b"same",
            "same.stl",
            "fdm",
            "automotive",
            authed_user,
            session,
        )

    first_hash = check_cache.await_args_list[0].args[3]
    second_hash = check_cache.await_args_list[1].args[3]
    assert first_hash != second_hash
    assert first_hash == compute_process_set_hash(
        ["fdm", "rule_pack=aerospace@1.0.0"]
    )
    assert second_hash == compute_process_set_hash(
        ["fdm", "rule_pack=automotive@1.0.0"]
    )


@pytest.mark.asyncio
async def test_worker_mode_returns_exact_fresh_persisted_analysis_id(
    db_session, authed_user, _pipeline_patches
):
    """Delayed workers link the row produced by this run, not a later variant."""
    from src.services.analysis_service import run_analysis

    helpers = _make_mock_route_helpers()
    with patch("src.services.analysis_service._get_route_helpers", return_value=helpers):
        outcome = await run_analysis(
            file_bytes=b"exact-row",
            filename="exact.stl",
            processes="fdm",
            rule_pack=None,
            user=authed_user,
            session=db_session,
            return_persisted_id=True,
        )

    assert isinstance(outcome, AnalysisRun)
    assert outcome.analysis_id is not None
    persisted = [
        obj
        for obj in db_session._added
        if obj.__class__.__name__ == "Analysis"
    ]
    assert len(persisted) == 1
    assert outcome.analysis_id == persisted[0].id
    assert outcome.result["filename"] == "cube.stl"


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
@pytest.mark.parametrize("org_id", [None, "org-race"])
async def test_concurrent_duplicate_upload(db_session, authed_user, _pipeline_patches, org_id):
    """Plain and real TaskGroup-wrapped insert conflicts reuse the winning row."""
    from sqlalchemy.exc import IntegrityError
    from src.services import analysis_service as svc

    winner = MagicMock(id=42, result_json={"verdict": "pass", "concurrent": True}, duration_ms=50.0, face_count=12)
    db_session.rollback = AsyncMock()
    conflict = IntegrityError("duplicate key", params={}, orig=Exception("uq_analyses_dedup"))
    with (
        patch.object(svc, "_get_route_helpers", return_value=_make_mock_route_helpers()),
        patch.object(svc, "_check_cache", new=AsyncMock(side_effect=[None, winner])) as cache,
        patch.object(svc, "_persist_analysis", new=AsyncMock(side_effect=conflict)),
        patch.object(svc, "_persist_source_evidence", new=AsyncMock()),
        patch.object(svc, "_write_usage_event", new=AsyncMock()) as usage,
    ):
        outcome = await svc.run_analysis(
            b"concurrent_file", "cube.stl", "fdm", None, authed_user, db_session,
            org_id=org_id, return_persisted_id=True,
        )
    assert isinstance(outcome, AnalysisRun)
    assert outcome.analysis_id == 42 and outcome.result == winner.result_json
    assert cache.await_count == 2
    assert cache.await_args.kwargs["org_id"] == org_id
    db_session.rollback.assert_awaited_once()
    assert usage.await_args.args[2:4] == ("analysis_cached", 42)


@pytest.mark.asyncio
@pytest.mark.parametrize("also_conflict", [False, True])
async def test_storage_failure_is_not_hidden_by_dedup_recovery(db_session, authed_user, _pipeline_patches, also_conflict):
    from sqlalchemy.exc import IntegrityError
    from src.services import analysis_service as svc

    persist = AsyncMock(return_value=MagicMock(id=42))
    if also_conflict:
        persist.side_effect = IntegrityError("duplicate key", params={}, orig=Exception())
    with (
        patch.object(svc, "_get_route_helpers", return_value=_make_mock_route_helpers()),
        patch.object(svc, "_check_cache", new=AsyncMock(return_value=None)) as cache,
        patch.object(svc, "_persist_analysis", new=persist),
        patch.object(svc, "_persist_source_evidence", new=AsyncMock(side_effect=OSError("source unavailable"))),
        patch.object(svc, "_write_usage_event", new=AsyncMock()) as usage,
    ):
        with pytest.raises(ExceptionGroup) as failure:
            await svc.run_analysis(b"concurrent_file", "cube.stl", "fdm", None, authed_user, db_session, org_id="org-race")
    assert failure.value.subgroup(OSError) is not None
    if also_conflict:
        assert failure.value.subgroup(IntegrityError) is not None
    cache.assert_awaited_once()
    usage.assert_not_awaited()

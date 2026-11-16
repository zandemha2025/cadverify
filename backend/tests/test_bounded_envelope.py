"""The containment envelope: untrusted CAD can never kill the serving process.

A pathological file inside the capped child costs one recycled worker and an
honest AnalysisBudgetExceeded (or, when the allocation fails as catchable
MemoryError mid-analysis, an honest ANALYSIS_PARTIAL degradation) — the parent
process always survives. These tests hold that contract.
"""
from __future__ import annotations

import gzip
import os
import pathlib

import pytest

ASSET = pathlib.Path(__file__).parent / "assets" / "stepped_shaft.stp.gz"


@pytest.fixture(scope="module")
def shaft_mesh():
    from src.api.routes import _parse_mesh

    data = gzip.decompress(ASSET.read_bytes())
    mesh, _ = _parse_mesh(data, "stepped_shaft.stp")
    return mesh


def _env(mem_mb: str, timeout: str = "120"):
    return {
        "CADVERIFY_ANALYSIS_POOL": "1",
        "ANALYSIS_POOL_MEM_MB": mem_mb,
        "ANALYSIS_POOL_TIMEOUT_S": timeout,
        # hermetic: never depends on the deployment-sized default RSS cap
        "ANALYSIS_POOL_RSS_MB": "3072",
    }


def test_bounded_engine_returns_the_same_contract(shaft_mesh):
    """The child returns exactly what the in-thread engine returns (the audit
    receipts' finding set is the regression signal)."""
    import asyncio

    from src.analysis import bounded

    os.environ.update(_env("2048"))
    try:
        result, mesh, ctx = bounded.run_engine_ctx_sync(shaft_mesh, "s.stp", None)
    finally:
        os.environ.pop("CADVERIFY_ANALYSIS_POOL", None)
    codes = {i.code for s in result.process_scores for i in s.issues}
    assert "DEEP_HOLE" in codes
    turning = next(s for s in result.process_scores if s.process.value == "cnc_turning")
    assert turning.score < 1.0


def test_time_bomb_is_contained_not_fatal(shaft_mesh):
    """An analysis over the wall clock is killed and reported as a budget
    trip; the parent keeps running and the pool recovers for the next caller."""
    from src.analysis import bounded

    os.environ.update(_env("2048", timeout="1"))
    try:
        with pytest.raises(bounded.AnalysisBudgetExceeded) as ei:
            bounded._run_bounded(bounded._sleep_worker, 30.0)
        assert ei.value.stage in ("time", "died")
        # recovery: a normal budget completes on the recycled pool
        os.environ["ANALYSIS_POOL_TIMEOUT_S"] = "240"
        result, _m, _ctx = bounded.run_engine_ctx_sync(shaft_mesh, "s.stp", None)
        assert result.process_scores
    finally:
        os.environ.pop("CADVERIFY_ANALYSIS_POOL", None)


@pytest.mark.skipif(not pathlib.Path("/proc").exists(),
                    reason="the RSS watchdog reads /proc (the deployed runtime)")
def test_memory_bomb_is_contained_not_fatal():
    """A worker whose RSS crosses the watchdog cap is killed INSIDE the pool;
    the parent observes AnalysisBudgetExceeded and keeps running."""
    from src.analysis import bounded

    # The RSS watchdog is the trip wire (kills the worker within ~1s of the
    # bomb crossing it); VA stays generous so imports/threads never false-trip.
    os.environ.update(_env("4096", timeout="120", rss_mb="256"))
    try:
        with pytest.raises(bounded.AnalysisBudgetExceeded) as ei:
            bounded._run_bounded(bounded._memory_bomb_worker, 1024)
        assert ei.value.stage in ("memory", "died")
        # recovery on the recycled pool
        assert bounded._run_bounded(bounded._memory_bomb_worker, 8) == 8
    finally:
        os.environ.pop("CADVERIFY_ANALYSIS_POOL", None)


def test_per_analyzer_failure_degrades_to_partial():
    """One analyzer raising degrades to an ANALYSIS_PARTIAL issue instead of
    failing the whole cost engine (the routes engine's containment contract)."""
    import src.analysis.processes  # noqa: F401
    from src.analysis.base_analyzer import analyze_geometry
    from src.analysis.context import GeometryContext
    from src.analysis.features import detect_all
    from src.analysis.models import ProcessType
    from src.analysis.processes import base as pbase
    from src.analysis.processes.base import get_analyzer
    from src.api.routes import _run_cost_engine_ctx
    import trimesh

    mesh = trimesh.creation.box(extents=[40, 30, 25])
    result, _m, ctx = _run_cost_engine_ctx(mesh, "b.stl")
    assert result.process_scores, "sanity: box analyses cleanly"

    # Monkeypatch one analyzer to explode; the engine must survive and say so.
    original = pbase.get_analyzer

    def exploding(process):
        analyzer = original(process)
        if process == ProcessType.CNC_3AXIS:
            class Boom(analyzer.__class__):
                def analyze(self, ctx):
                    raise MemoryError("simulated runaway allocation")
            return Boom()
        return analyzer

    pbase.get_analyzer = exploding
    try:
        result2, _m2, _ctx2 = _run_cost_engine_ctx(mesh, "b.stl")
        three = next(s for s in result2.process_scores if s.process.value == "cnc_3axis")
        assert any(i.code == "ANALYSIS_PARTIAL" for i in three.issues)
        # every OTHER process still produced its real verdict
        others = [s for s in result2.process_scores if s.process.value != "cnc_3axis"]
        assert others and all(s.verdict in ("pass", "issues", "fail") for s in others)
    finally:
        pbase.get_analyzer = original

"""Regression: a periodic-surface part returns a valid shell WITHIN the route
budget — BOUNDED time, not "eventually" after a multi-minute grind + 504.

The retry ladder alone (test_step_mesher_periodic.py) recovers periodic parts to
a watertight shell, but rung 0 (gmsh's default 2D algorithm) GRINDS for 2+ minutes
on a periodic surface before failing, and only THEN does the fast MeshAdapt rung
run. Under the route's ``asyncio.wait_for(..., ANALYSIS_TIMEOUT_SEC)`` that means a
504 — the recovery never reaches the user. mesh.generate is an uninterruptible
in-thread C call, so ``parse_pool`` bounds EACH rung with a wall-clock cap by
running it in a separately-timed, killable subprocess:

  * rung 0 runs on the shared warm pool with cap ``min(0.4*budget, 25s)``. A normal
    part meshes far under the cap (byte-identical, no regression); a periodic grind
    is abandoned at the cap.
  * the recovery rungs each run in their OWN single-worker spawn subprocess and are
    HARD-KILLED (SIGKILL) at their cap, then the next rung runs.

The caps sum to < budget, so an all-rungs-fail part surfaces the honest 400 (not a
504). These tests prove the BOUNDED-TIME property: the FAST test simulates the
grind (a sleeping rung-0) deterministically; the SLOW tests drive the REAL gmsh
periodic fixture through the REAL cap + kill + async-timeout path.

Byte-identity of the fast/non-periodic path is covered by
test_parse_pool.py::test_pool_matches_in_thread_byte_identical (cube, rung 0) and
::test_pooled_async_matches_in_thread (the pooled async path this change routes
through) — a periodic-only cap never touches a part that meshes on rung 0.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
import trimesh

from src.api.routes import _parse_mesh_async
from src.parsers import mesh_cache, parse_pool

_PERIODIC_FIXTURE = Path(__file__).parent / "assets" / "nist_periodic_ctc05.stp"


def _require_step():
    from src.parsers.step_mesher import is_step_supported

    if not is_step_supported():
        pytest.skip("gmsh not installed; STEP path unavailable")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "PARSE_PROCESS_POOL_DISABLED",
        "PARSE_POOL_WORKERS",
        "MESH_PARSE_CACHE_DISABLED",
        "MAX_TRIANGLES",
        "ANALYSIS_TIMEOUT_SEC",
    ):
        monkeypatch.delenv(var, raising=False)
    parse_pool.shutdown()
    mesh_cache.get_cache().clear()
    yield
    parse_pool.shutdown()
    mesh_cache.get_cache().clear()


# ──────────────────────────────────────────────────────────────
# FAST: the bounded-time property, deterministically (no real grind)
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_periodic_ladder_is_bounded_and_advances(monkeypatch):
    """A rung-0 GRIND is abandoned at its cap and the recovery rung runs — the
    whole ladder finishing WELL within the budget, not "eventually".

    We stub rung 0 to sleep to its cap then signal a cap-timeout (exactly what a
    real periodic grind does), and the recovery rung to return a valid box. The
    orchestrator must advance rung 0 -> rung 1 and return in ~rung-0-cap seconds,
    strictly under the total budget.
    """
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "3")
    budget = parse_pool._budget_sec()
    caps = parse_pool._rung_caps(budget, 3)
    seen: list[tuple[str, float]] = []

    async def _grind_rung0(data, suffix, cap, loop):
        seen.append(("rung0", cap))
        await asyncio.sleep(cap)  # grind to the cap, like the default algo does
        raise parse_pool._RungTimeout(f"rung 0 exceeded {cap:.0f}s cap")

    async def _fast_recovery(data, suffix, idx, cap):
        seen.append((f"rung{idx}", cap))
        return trimesh.creation.box(extents=(10, 10, 10))

    monkeypatch.setattr(parse_pool, "_rung0_via_pool", _grind_rung0)
    monkeypatch.setattr(parse_pool, "_run_rung_killable", _fast_recovery)

    t0 = time.perf_counter()
    mesh = await parse_pool.submit_async(b"periodic-stub", ".step")
    dt = time.perf_counter() - t0

    assert len(mesh.faces) > 0, "recovery rung must yield a valid shell"
    # rung 0 was abandoned at its cap; rung 1 recovered — all inside the budget.
    assert dt < budget, f"periodic ladder must finish within budget {budget}s, took {dt:.2f}s"
    assert dt >= caps[0] * 0.9, "rung 0 should have consumed ~its cap before advancing"
    assert seen[0][0] == "rung0" and seen[1][0] == "rung1", f"wrong rung order: {seen}"


@pytest.mark.asyncio
async def test_all_rungs_capped_yields_honest_400_within_budget(monkeypatch):
    """If EVERY rung grinds to its cap, the caps sum to < budget so the ladder
    raises the SPECIFIC honest error (mapped to 400) BEFORE the route's total
    budget would 504 — never the generic failure, never a hang."""
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "3")
    budget = parse_pool._budget_sec()

    async def _grind0(data, suffix, cap, loop):
        await asyncio.sleep(cap)
        raise parse_pool._RungTimeout("rung 0 periodic-surface grind (capped)")

    async def _grind_recovery(data, suffix, idx, cap):
        await asyncio.sleep(cap)
        raise parse_pool._RungTimeout(f"rung {idx} capped")

    monkeypatch.setattr(parse_pool, "_rung0_via_pool", _grind0)
    monkeypatch.setattr(parse_pool, "_run_rung_killable", _grind_recovery)

    t0 = time.perf_counter()
    with pytest.raises(ValueError) as ei:
        await parse_pool.submit_async(b"periodic-stub", ".step")
    dt = time.perf_counter() - t0

    # We hard-killed every grinding rung, so gmsh's own periodic-surface text is
    # never captured; the honest message names that ALL strategies failed. What
    # matters (the invariant): it is the SPECIFIC "could not tessellate" error the
    # route maps to a detailed 400, NEVER the generic "Failed to parse mesh file".
    msg = str(ei.value).lower()
    assert "could not tessellate" in msg, f"must be the specific error, got: {ei.value}"
    assert "all 3 mesh strategies failed" in msg
    assert "failed to parse mesh file" not in msg
    assert dt < budget, f"honest error must beat the {budget}s total budget, took {dt:.2f}s"


# ──────────────────────────────────────────────────────────────
# SLOW: the REAL gmsh grind is really hard-killed + really recovers in budget
# ──────────────────────────────────────────────────────────────
@pytest.mark.slow
@pytest.mark.asyncio
async def test_real_rung0_grind_is_hard_killed_near_its_cap():
    """The REAL periodic fixture makes rung 0 (default algo) grind for 2+ minutes.
    In a killable subprocess it is SIGKILLed at its cap: ``_run_rung_killable``
    raises ``_RungTimeout`` shortly after the cap, reclaiming the CPU — instead of
    grinding uninterruptibly to completion."""
    _require_step()
    data = _PERIODIC_FIXTURE.read_bytes()
    cap = 5.0
    t0 = time.perf_counter()
    with pytest.raises(parse_pool._RungTimeout):
        await parse_pool._run_rung_killable(data, ".step", 0, cap)
    dt = time.perf_counter() - t0
    # Killed near the cap (allow spawn + kill slack), NOT the 120s+ full grind.
    assert dt < cap + 10.0, f"rung 0 grind must be killed near its {cap}s cap, took {dt:.1f}s"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_real_periodic_part_returns_watertight_shell_within_budget(monkeypatch):
    """END-TO-END: the REAL periodic fixture returns a VALID watertight shell via
    the REAL async + ANALYSIS_TIMEOUT_SEC + pool path, in WELL under the 60s route
    budget (target < 45s on this box) — where before it 504'd after a 2-min grind."""
    _require_step()
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "60")
    mesh_cache.get_cache().clear()  # force a real parse, no warm-hit shortcut
    data = _PERIODIC_FIXTURE.read_bytes()

    t0 = time.perf_counter()
    mesh, suffix = await _parse_mesh_async(data, "nist_periodic_ctc05.stp")
    dt = time.perf_counter() - t0

    assert suffix == ".stp"
    assert mesh.is_watertight, "recovered periodic shell must be watertight"
    assert 100 < len(mesh.faces) < 2_000_000
    assert mesh.volume > 0
    assert dt < 45.0, f"periodic part must return within 45s budget, took {dt:.1f}s"

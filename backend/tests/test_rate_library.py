"""W4 governed rate-library — pure logic, engine wiring, and resolution/cache.

No live DB: the versioning / effective-dating / validation logic is pure and the
DB-adapter resolution path is exercised with a lightweight fake session (mirrors
the repo's mocked-session convention). The Postgres CRUD lifecycle is covered by
the DATABASE_URL-guarded ``test_rate_library_api.py``.

The load-bearing guarantee: with the flag OFF (default) and/or no governed card,
the cost path is BYTE-IDENTICAL to pre-W4.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult
from src.analysis.processes.base import get_analyzer
from src.analysis.processes import base as pbase
from src.matcher.profile_matcher import rank_processes, score_process
import src.analysis.processes  # noqa: F401 — populate registry

from src.costing import estimate_decision, EstimateOptions, report_to_dict
from src.costing.rates import RATE_CARD_V0, build_rate_card
from src.services import rate_library_service as svc


UTC = timezone.utc


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _analyze(mesh):
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    universal = run_universal_checks(mesh)
    scores = [
        score_process(get_analyzer(p).analyze(ctx), geometry, p)
        for p in pbase._REGISTRY
        if get_analyzer(p)
    ]
    result = AnalysisResult(
        filename="cube.stl",
        file_type="stl",
        geometry=geometry,
        segments=ctx.segments,
        universal_issues=universal,
        process_scores=scores,
    )
    rank_processes(result)
    return result, mesh, ctx.features


def _block():
    return trimesh.creation.box(extents=[40.0, 30.0, 25.0])


def _row(version, status, effective_from, effective_to):
    return SimpleNamespace(
        version=version,
        status=status,
        effective_from=effective_from,
        effective_to=effective_to,
    )


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    """Minimal async session: every execute returns the same published rows."""

    def __init__(self, rows):
        self._rows = rows
        self.execute_calls = 0

    async def execute(self, _stmt):
        self.execute_calls += 1
        return _FakeResult(self._rows)


# ---------------------------------------------------------------------------
# flag
# ---------------------------------------------------------------------------


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("RATE_LIBRARY_ENABLED", raising=False)
    assert svc.rate_library_enabled() is False


def test_flag_on(monkeypatch):
    for v in ("1", "true", "on", "YES"):
        monkeypatch.setenv("RATE_LIBRARY_ENABLED", v)
        assert svc.rate_library_enabled() is True
    monkeypatch.setenv("RATE_LIBRARY_ENABLED", "0")
    assert svc.rate_library_enabled() is False


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def test_default_payload_is_deep_copy():
    p = svc.default_rate_payload()
    assert p == RATE_CARD_V0
    p["global"]["labor_rate"] = 999.0
    assert RATE_CARD_V0["global"]["labor_rate"] != 999.0  # untouched


def test_validate_accepts_default():
    svc.validate_rate_table(svc.default_rate_payload())  # no raise


@pytest.mark.parametrize("bad", [None, [], "x", 3, {}])
def test_validate_rejects_non_table(bad):
    with pytest.raises(ValueError):
        svc.validate_rate_table(bad)


def test_validate_rejects_missing_global_key():
    p = svc.default_rate_payload()
    del p["global"]["labor_rate"]
    with pytest.raises(ValueError):
        svc.validate_rate_table(p)


def test_validate_rejects_missing_top_key():
    p = svc.default_rate_payload()
    # drop an arbitrary non-global top-level key
    top = [k for k in p if k != "global"][0]
    del p[top]
    with pytest.raises(ValueError):
        svc.validate_rate_table(p)


# ---------------------------------------------------------------------------
# effective-date resolution (pure)
# ---------------------------------------------------------------------------


def test_select_effective_empty():
    assert svc.select_effective([], datetime.now(UTC)) is None


def test_select_effective_ignores_drafts():
    now = datetime.now(UTC)
    rows = [_row(1, "draft", None, None)]
    assert svc.select_effective(rows, now) is None


def test_select_effective_single_open():
    now = datetime.now(UTC)
    r = _row(1, "published", now - timedelta(days=1), None)
    assert svc.select_effective([r], now) is r


def test_select_effective_before_effective_from():
    now = datetime.now(UTC)
    r = _row(1, "published", now + timedelta(days=1), None)
    assert svc.select_effective([r], now) is None


def test_select_effective_superseded_timeline():
    now = datetime.now(UTC)
    switch = now - timedelta(hours=1)
    v1 = _row(1, "published", now - timedelta(days=2), switch)  # closed at switch
    v2 = _row(2, "published", switch, None)                     # open since switch
    assert svc.select_effective([v1, v2], now) is v2
    # a moment before the switch resolves to v1
    assert svc.select_effective([v1, v2], switch - timedelta(minutes=1)) is v1


def test_select_effective_to_boundary_is_exclusive():
    now = datetime.now(UTC)
    r = _row(1, "published", now - timedelta(days=1), now)  # effective_to == now
    assert svc.select_effective([r], now) is None  # [from, to) — to is exclusive


# ---------------------------------------------------------------------------
# resolution + cache (fake session)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_none_when_flag_off(monkeypatch):
    monkeypatch.delenv("RATE_LIBRARY_ENABLED", raising=False)
    sess = _FakeSession([_row(1, "published", datetime.now(UTC) - timedelta(days=1), None)])
    out = await svc.resolve_rate_table_for_org(sess, "org_x")
    assert out is None
    assert sess.execute_calls == 0  # never touches the DB when flag is off


@pytest.mark.asyncio
async def test_resolve_none_without_org(monkeypatch):
    monkeypatch.setenv("RATE_LIBRARY_ENABLED", "1")
    sess = _FakeSession([])
    assert await svc.resolve_rate_table_for_org(sess, None) is None
    assert await svc.resolve_rate_table_for_org(sess, "") is None


@pytest.mark.asyncio
async def test_resolve_returns_payload_and_caches(monkeypatch):
    monkeypatch.setenv("RATE_LIBRARY_ENABLED", "1")
    svc.invalidate("org_cache")
    payload = svc.default_rate_payload()
    payload["global"]["labor_rate"] = 77.0
    row = SimpleNamespace(
        version=3,
        status="published",
        effective_from=datetime.now(UTC) - timedelta(days=1),
        effective_to=None,
        payload=payload,
    )
    sess = _FakeSession([row])
    out1 = await svc.resolve_rate_table_for_org(sess, "org_cache")
    assert out1 is payload
    assert sess.execute_calls == 1
    # second call within the effective window is served from cache (no new query)
    out2 = await svc.resolve_rate_table_for_org(sess, "org_cache")
    assert out2 is payload
    assert sess.execute_calls == 1
    svc.invalidate("org_cache")


# ---------------------------------------------------------------------------
# engine wiring — build_rate_card
# ---------------------------------------------------------------------------


def test_build_rate_card_base_none_equals_default():
    a = build_rate_card()
    b = build_rate_card(base_rate_table=None)
    assert a.data == b.data


def test_build_rate_card_default_payload_is_identical():
    # a governed card seeded from the canonical default must produce the same
    # engine table as the hardcoded default
    a = build_rate_card().data
    b = build_rate_card(base_rate_table=svc.default_rate_payload()).data
    assert a == b


def test_build_rate_card_uses_governed_base():
    gov = svc.default_rate_payload()
    gov["global"]["labor_rate"] = 70.0
    rc = build_rate_card(base_rate_table=gov)
    assert rc.data["global"]["labor_rate"] == 70.0
    assert build_rate_card().data["global"]["labor_rate"] != 70.0


def test_build_rate_card_user_override_wins_over_governed_base():
    gov = svc.default_rate_payload()
    gov["global"]["labor_rate"] = 70.0
    rc = build_rate_card({"labor_rate": 90.0}, base_rate_table=gov)
    assert rc.data["global"]["labor_rate"] == 90.0
    assert "labor_rate" in rc.user_keys


# ---------------------------------------------------------------------------
# full cost path — byte-identity + real consumption
# ---------------------------------------------------------------------------


def test_estimate_base_table_none_is_byte_identical():
    result, mesh, feats = _analyze(_block())
    a = report_to_dict(
        estimate_decision(result, mesh, feats, EstimateOptions(quantities=[10, 1000]))
    )
    b = report_to_dict(
        estimate_decision(
            result,
            mesh,
            feats,
            EstimateOptions(quantities=[10, 1000], base_rate_table=None),
        )
    )
    assert a == b


def test_estimate_default_governed_table_is_byte_identical():
    result, mesh, feats = _analyze(_block())
    a = report_to_dict(
        estimate_decision(result, mesh, feats, EstimateOptions(quantities=[10, 1000]))
    )
    b = report_to_dict(
        estimate_decision(
            result,
            mesh,
            feats,
            EstimateOptions(
                quantities=[10, 1000], base_rate_table=svc.default_rate_payload()
            ),
        )
    )
    assert a == b


def test_estimate_governed_labor_bump_raises_cost():
    result, mesh, feats = _analyze(_block())
    base = estimate_decision(
        result, mesh, feats, EstimateOptions(quantities=[100])
    )
    gov = svc.default_rate_payload()
    gov["global"]["labor_rate"] = RATE_CARD_V0["global"]["labor_rate"] * 1.5
    bumped = estimate_decision(
        result, mesh, feats, EstimateOptions(quantities=[100], base_rate_table=gov)
    )
    base_by = {e["process"]: e["unit_cost_usd"] for e in base.estimates}
    bump_by = {e["process"]: e["unit_cost_usd"] for e in bumped.estimates}
    assert base_by, "expected costable estimates"
    for proc, cost in base_by.items():
        assert bump_by[proc] >= cost
    assert any(bump_by[p] > base_by[p] for p in base_by)


def test_estimate_options_default_base_is_none():
    assert EstimateOptions().base_rate_table is None

"""W4 governed shop-library — pure logic, engine wiring, and resolution/cache.

No live DB: the versioning / effective-dating / validation logic is pure and the
DB-adapter resolution path is exercised with a lightweight fake session (mirrors
the repo's mocked-session convention). The Postgres CRUD lifecycle is covered by
the DATABASE_URL-guarded ``test_shop_library_api.py``.

The load-bearing guarantee: with the flag OFF (default) and/or no governed
profile for a slug, the cost path is BYTE-IDENTICAL to pre-W4 (flat-file
``resolve_shop`` only).
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
from src.costing.shop_profile import ShopProfile, resolve_shop
from src.services import shop_library_service as svc


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


def _row(version, status, effective_from, effective_to, slug="acme"):
    return SimpleNamespace(
        version=version,
        status=status,
        effective_from=effective_from,
        effective_to=effective_to,
        slug=slug,
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


# A real shop-overrides dict (the exact dotted-key form to_shop_overrides emits).
def _real_overrides() -> dict:
    prof = ShopProfile(
        name="Midwest Precision CNC",
        region="US",
        labor_rate=52.0,
        margin=0.3,
        overhead=0.15,
        utilization=0.8,
        machine_rates={"CNC_3AXIS": 95, "SLS": 28, "INJECTION_MOLDING": 60},
        material_prices={"@polymer": 7.0, "@aluminum": 9.0},
        region_multipliers={"labor": 1.0, "material": 1.0, "tooling": 1.0},
    )
    ov = prof.to_shop_overrides()
    ov["name"] = prof.name
    ov["region"] = prof.region
    return ov


# ---------------------------------------------------------------------------
# flag
# ---------------------------------------------------------------------------


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("SHOP_LIBRARY_ENABLED", raising=False)
    assert svc.shop_library_enabled() is False


def test_flag_on(monkeypatch):
    for v in ("1", "true", "on", "YES"):
        monkeypatch.setenv("SHOP_LIBRARY_ENABLED", v)
        assert svc.shop_library_enabled() is True
    monkeypatch.setenv("SHOP_LIBRARY_ENABLED", "0")
    assert svc.shop_library_enabled() is False


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def test_validate_accepts_real_overrides_dict():
    svc.validate_shop_payload(_real_overrides())  # no raise


def test_validate_accepts_empty_dict():
    # a shop that overrides nothing stays all-DEFAULT — valid.
    svc.validate_shop_payload({})


@pytest.mark.parametrize("bad", [None, [], "x", 3])
def test_validate_rejects_non_dict(bad):
    with pytest.raises(ValueError):
        svc.validate_shop_payload(bad)


def test_validate_rejects_unknown_global_key():
    with pytest.raises(ValueError):
        svc.validate_shop_payload({"labor_rate": 52.0, "totally_bogus": 1.0})


def test_validate_rejects_unknown_process_in_dotted_key():
    with pytest.raises(ValueError):
        svc.validate_shop_payload({"machine_rate.NOT_A_PROCESS": 5.0})


def test_validate_ignores_name_region_metadata():
    # name/region are identity metadata, not rate keys — they must not be
    # dry-run-bound as overrides (which would reject them).
    svc.validate_shop_payload({"name": "Acme", "region": "MX", "labor_rate": 40.0})


def test_validate_rejects_non_string_name():
    with pytest.raises(ValueError):
        svc.validate_shop_payload({"name": 123, "labor_rate": 40.0})


# ---------------------------------------------------------------------------
# default_shop_payload (flat-file migration seed)
# ---------------------------------------------------------------------------


def test_default_payload_migrates_known_flatfile_slug():
    # "midwest-precision-cnc" ships as a flat file — its first draft is seeded
    # from it verbatim (overrides + name + region).
    payload = svc.default_shop_payload("midwest-precision-cnc")
    assert payload["name"] == "Midwest Precision CNC"
    assert payload["region"] == "US"
    assert payload["labor_rate"] == 52.0
    svc.validate_shop_payload(payload)  # migrated seed is engine-consumable


def test_default_payload_unknown_slug_is_empty():
    assert svc.default_shop_payload("no-such-shop-xyz") == {}


# ---------------------------------------------------------------------------
# effective-date resolution (pure) — PER (org, slug)
# ---------------------------------------------------------------------------


def test_select_effective_empty():
    assert svc.select_effective([], datetime.now(UTC)) is None


def test_select_effective_ignores_drafts():
    now = datetime.now(UTC)
    assert svc.select_effective([_row(1, "draft", None, None)], now) is None


def test_select_effective_single_open():
    now = datetime.now(UTC)
    r = _row(1, "published", now - timedelta(days=1), None)
    assert svc.select_effective([r], now) is r


def test_select_effective_ignores_archived():
    now = datetime.now(UTC)
    archived = _row(2, "archived", now - timedelta(days=1), None)
    assert svc.select_effective([archived], now) is None


def test_select_effective_per_slug_isolation():
    """A published version for slug A is never returned for slug B."""
    now = datetime.now(UTC)
    a = _row(1, "published", now - timedelta(days=1), None, slug="shop-a")
    b = _row(2, "published", now - timedelta(days=1), None, slug="shop-b")
    rows = [a, b]
    assert svc.select_effective(rows, now, slug="shop-a") is a
    assert svc.select_effective(rows, now, slug="shop-b") is b
    # a slug with no published version resolves to nothing
    assert svc.select_effective(rows, now, slug="shop-c") is None


def test_select_effective_superseded_timeline_per_slug():
    now = datetime.now(UTC)
    switch = now - timedelta(hours=1)
    v1 = _row(1, "published", now - timedelta(days=2), switch, slug="s")
    v2 = _row(2, "published", switch, None, slug="s")
    assert svc.select_effective([v1, v2], now, slug="s") is v2
    assert svc.select_effective([v1, v2], switch - timedelta(minutes=1), slug="s") is v1


# ---------------------------------------------------------------------------
# resolution + cache (fake session) — keyed (org, slug)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_none_when_flag_off(monkeypatch):
    monkeypatch.delenv("SHOP_LIBRARY_ENABLED", raising=False)
    sess = _FakeSession(
        [_row(1, "published", datetime.now(UTC) - timedelta(days=1), None, slug="s")]
    )
    out = await svc.resolve_shop_overrides_for(sess, "org_x", "s")
    assert out is None
    assert sess.execute_calls == 0  # never touches the DB when flag is off


@pytest.mark.asyncio
async def test_resolve_none_without_org_or_slug(monkeypatch):
    monkeypatch.setenv("SHOP_LIBRARY_ENABLED", "1")
    sess = _FakeSession([])
    assert await svc.resolve_shop_overrides_for(sess, None, "s") is None
    assert await svc.resolve_shop_overrides_for(sess, "", "s") is None
    assert await svc.resolve_shop_overrides_for(sess, "org", None) is None
    assert await svc.resolve_shop_overrides_for(sess, "org", "") is None
    assert sess.execute_calls == 0


@pytest.mark.asyncio
async def test_resolve_returns_payload_and_caches(monkeypatch):
    monkeypatch.setenv("SHOP_LIBRARY_ENABLED", "1")
    svc.invalidate("org_cache", "s")
    payload = _real_overrides()
    row = SimpleNamespace(
        version=3,
        status="published",
        effective_from=datetime.now(UTC) - timedelta(days=1),
        effective_to=None,
        slug="s",
        payload=payload,
    )
    sess = _FakeSession([row])
    out1 = await svc.resolve_shop_overrides_for(sess, "org_cache", "s")
    assert out1 is payload
    assert sess.execute_calls == 1
    # second call within the effective window is served from cache (no new query)
    out2 = await svc.resolve_shop_overrides_for(sess, "org_cache", "s")
    assert out2 is payload
    assert sess.execute_calls == 1
    # a DIFFERENT slug is a distinct cache key — it queries, and the only row
    # (slug "s") is filtered out per-slug, so it resolves to None (no leak).
    out3 = await svc.resolve_shop_overrides_for(sess, "org_cache", "other")
    assert out3 is None
    assert sess.execute_calls == 2
    svc.invalidate("org_cache")


# ---------------------------------------------------------------------------
# governed binding object — SHOP provenance through build_rate_card
# ---------------------------------------------------------------------------


def test_governed_profile_is_resolvable_and_strips_metadata():
    gp = svc.governed_shop_profile("acme", _real_overrides())
    # resolve_shop accepts it (ShopProfile subclass) and returns it unchanged
    assert resolve_shop(gp) is gp
    assert gp.name == "Midwest Precision CNC"
    assert gp.region == "US"
    ov = gp.to_shop_overrides()
    assert "name" not in ov and "region" not in ov      # metadata stripped
    assert ov["labor_rate"] == 52.0
    assert ov["machine_rate.CNC_3AXIS"] == 95.0


def test_build_rate_card_binds_governed_overrides_as_shop():
    ov = {k: v for k, v in _real_overrides().items() if k not in ("name", "region")}
    rc = build_rate_card(shop_overrides=ov)
    assert rc.data["global"]["labor_rate"] == 52.0
    # every governed override key is tagged SHOP provenance (never USER/DEFAULT)
    assert "labor_rate" in rc.shop_keys
    assert "machine_rate.CNC_3AXIS" in rc.shop_keys
    assert not rc.user_keys


def test_governed_labor_bump_raises_cost_and_is_never_validated():
    result, mesh, feats = _analyze(_block())
    base = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100]))
    gp = svc.governed_shop_profile(
        "expensive-shop",
        {"labor_rate": RATE_CARD_V0["global"]["labor_rate"] * 2.0, "name": "Pricey"},
    )
    bumped = estimate_decision(
        result, mesh, feats, EstimateOptions(quantities=[100], shop=gp)
    )
    base_by = {e["process"]: e["unit_cost_usd"] for e in base.estimates}
    bump_by = {e["process"]: e["unit_cost_usd"] for e in bumped.estimates}
    assert base_by, "expected costable estimates"
    for proc, cost in base_by.items():
        assert bump_by[proc] >= cost
    assert any(bump_by[p] > base_by[p] for p in base_by)
    # HONESTY: a governed shop profile is a DECLARED assumption, never measured —
    # binding it never flips any estimate's confidence band to validated.
    for e in bumped.estimates:
        ci = e.get("confidence")
        if ci:
            assert ci["validated"] is False


def test_serialize_version_is_shop_provenance_never_validated():
    row = SimpleNamespace(
        id=1, ulid="01ABC", version=1, slug="acme", name="v1", status="draft",
        change_note="", effective_from=None, effective_to=None, created_by=None,
        created_at=None, published_at=None, payload={"labor_rate": 40.0},
    )
    out = svc.serialize_version(row)
    assert out["provenance"] == "shop"
    assert out["validated"] is False
    assert out["slug"] == "acme"
    assert "payload" not in out
    assert svc.serialize_version(row, include_payload=True)["payload"] == {"labor_rate": 40.0}

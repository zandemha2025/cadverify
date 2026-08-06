"""Pure + mock-session tests for the portfolio roll-up (W3, D5).

Two layers, mirroring test_catalog_service:

  * ``derive_savings`` is exercised directly with plain dicts (the exact
    ``report_to_dict`` decision shape) — it pins SAVINGS HONESTY: the delta is
    read verbatim from ``decision.recommendation`` vs ``decision.if_redesigned``,
    ranked by the deepest save_pct, carries the engine's own caveat + a ``basis``,
    and is None when no redesign is cheaper.
  * ``build_portfolio`` runs over a mocked session (no Postgres) so the ranking
    order, null-savings reason, posture aggregate, excluded-no-cost count, and
    truncated propagation are all asserted from the real fold + derivation.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.services import catalog_service as svc


# ---------------------------------------------------------------------------
# result_json builders (real report_to_dict decision shapes)
# ---------------------------------------------------------------------------


def _cost_json(
    *,
    make_now="cnc_3axis",
    quantities=(50, 5000),
    rec_units=(40.0, 30.0),
    alt=None,               # {qty(str): {process, unit_cost_usd, caveat}} | None
    dfm_ready=True,
    blockers=None,
    drivers=None,
    crossover=1200.0,
    validated=False,
):
    """A cost result_json with recommendation + optional if_redesigned tiers.

    ``alt`` keys are STRINGS on purpose — JSONB stringifies the int qty keys on
    round-trip, and the derivation must tolerate that.
    """
    recommendation = {
        str(q): {
            "process": make_now,
            "material": "aluminum_6061",
            "unit_cost_usd": u,
            "dfm_ready": dfm_ready,
            "dfm_verdict": "pass",
        }
        for q, u in zip(quantities, rec_units)
    }
    if_redesigned = {str(q): None for q in quantities}
    if alt:
        if_redesigned.update(alt)
    return {
        "quantities": list(quantities),
        "decision": {
            "make_now_process": make_now,
            "make_now_material": "aluminum_6061",
            "crossover_qty": crossover,
            "recommendation": recommendation,
            "if_redesigned": if_redesigned,
        },
        "estimates": [
            {
                "process": make_now,
                "material": "aluminum_6061",
                "quantity": quantities[0],
                "unit_cost_usd": rec_units[0],
                "dfm_ready": dfm_ready,
                "dfm_blockers": blockers or [],
                "confidence": {"validated": validated, "label": "assumption band"},
                "drivers": drivers
                if drivers is not None
                else [
                    {"name": "machine_rate", "provenance": "DEFAULT", "source": "generic"},
                    {"name": "labor_rate", "provenance": "SHOP", "source": "your shop"},
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# derive_savings — the honesty crux
# ---------------------------------------------------------------------------


def test_derive_savings_reads_if_redesigned_delta_verbatim():
    j = _cost_json(
        rec_units=(40.0, 30.0),
        alt={"5000": {"process": "injection_molding", "unit_cost_usd": 6.0,
                      "caveat": "invest in tooling"}},
    )
    s = svc.derive_savings(j)
    assert s is not None
    assert s["basis"] == "decision.if_redesigned"
    assert s["qty"] == 5000
    assert s["make_now_unit_usd"] == 30.0     # recommendation[5000].unit_cost_usd
    assert s["redesigned_unit_usd"] == 6.0    # if_redesigned[5000].unit_cost_usd
    assert s["save_unit_usd"] == 24.0
    assert s["save_pct"] == round(24.0 / 30.0, 4)
    assert s["redesigned_process"] == "injection_molding"
    assert s["caveat"] == "invest in tooling"  # engine's own caveat, verbatim


def test_derive_savings_picks_deepest_pct_across_quantities():
    # qty 50: 40 -> 20 (50% off). qty 5000: 30 -> 6 (80% off). Deepest wins.
    j = _cost_json(
        rec_units=(40.0, 30.0),
        alt={
            "50": {"process": "die_casting", "unit_cost_usd": 20.0, "caveat": "add draft"},
            "5000": {"process": "injection_molding", "unit_cost_usd": 6.0, "caveat": "tool up"},
        },
    )
    s = svc.derive_savings(j)
    assert s["qty"] == 5000
    assert s["save_pct"] == round(24.0 / 30.0, 4)


def test_derive_savings_none_when_no_cheaper_redesign():
    # No if_redesigned entries at all.
    assert svc.derive_savings(_cost_json(alt=None)) is None
    # A redesign that is NOT cheaper (alt >= make-now) yields no saving.
    j = _cost_json(
        rec_units=(40.0, 30.0),
        alt={"5000": {"process": "x", "unit_cost_usd": 35.0, "caveat": "c"}},
    )
    assert svc.derive_savings(j) is None


def test_derive_savings_tolerates_int_or_string_qty_keys():
    j = _cost_json(rec_units=(40.0, 30.0), alt=None)
    # int keys (a live, not-yet-round-tripped decision)
    j["decision"]["recommendation"] = {5000: {"unit_cost_usd": 30.0}}
    j["decision"]["if_redesigned"] = {5000: {"process": "im", "unit_cost_usd": 6.0, "caveat": ""}}
    s = svc.derive_savings(j)
    assert s is not None and s["qty"] == 5000 and s["save_unit_usd"] == 24.0


# ---------------------------------------------------------------------------
# Mock-session build_portfolio — ranking / summary / posture / truncated
# ---------------------------------------------------------------------------


class _Row:
    def __init__(self, mesh, result_json, *, ulid=None, ts=None):
        self.mesh_hash = mesh
        self.ulid = ulid or f"ul-{mesh}"
        self.filename = f"{mesh}.stl"
        self.file_type = "stl"
        self.created_at = ts or datetime(2026, 6, 1, tzinfo=timezone.utc)
        self.result_json = result_json


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    """Dispatches the two build_catalog scans by table name in the SQL text."""

    def __init__(self, analyses, costs):
        self._an = analyses
        self._cost = costs

    async def execute(self, stmt):
        s = str(stmt).lower()
        if "cost_decisions" in s:
            return _FakeResult(self._cost)
        # Slice 3: these mock orgs declare no BOM tree, so the bom_edges scan is
        # empty and build_portfolio takes the flat-declared (byte-identical) path.
        if "bom_edges" in s:
            return _FakeResult([])
        return _FakeResult(self._an)


@pytest.mark.asyncio
async def test_build_portfolio_ranks_and_summarizes():
    # Two costed parts with savings (deep + shallow) + one costed with no
    # savings + one drafted-only (analysis, excluded).
    deep = _Row(
        "m-deep",
        _cost_json(rec_units=(40.0, 30.0),
                   alt={"5000": {"process": "im", "unit_cost_usd": 6.0, "caveat": "tool up"}}),
    )
    shallow = _Row(
        "m-shallow",
        _cost_json(rec_units=(20.0, 18.0),
                   alt={"5000": {"process": "cast", "unit_cost_usd": 15.0, "caveat": "add draft"}}),
    )
    nosave = _Row("m-nosave", _cost_json(rec_units=(40.0, 30.0), alt=None))
    drafted = _Row("m-drafted", {"best_process": "cnc_3axis", "universal_issues": [],
                                 "process_scores": []})

    session = _FakeSession(analyses=[drafted], costs=[deep, shallow, nosave])
    out = await svc.build_portfolio(session, org_id="org-1")

    keys = [r["part_key"] for r in out["rows"]]
    # rows are costed parts only; drafted is excluded from the ranking
    assert set(keys) == {"m-deep", "m-shallow", "m-nosave"}
    # ranked by save_pct desc; the no-savings row sinks to last
    assert keys[0] == "m-deep"      # 80% off
    assert keys[1] == "m-shallow"   # ~16.7% off
    assert keys[2] == "m-nosave"    # savings null → last

    # savings basis + qty carried on the deep row
    deep_row = out["rows"][0]
    assert deep_row["savings"]["basis"] == "decision.if_redesigned"
    assert deep_row["savings"]["qty"] == 5000
    assert deep_row["make_now_process"] == "cnc_3axis"
    assert deep_row["crossover_qty"] == 1200.0
    # validated copied from the engine band (never computed)
    assert deep_row["validated"] is False

    # null-savings row carries a reason, never a fabricated number
    nosave_row = out["rows"][2]
    assert nosave_row["savings"] is None
    assert "no engine-computed cheaper alternative" in nosave_row["reason"]

    summary = out["summary"]
    assert summary["parts"] == 4
    assert summary["costed"] == 3
    assert summary["drafted"] == 1
    assert summary["excluded_no_cost_count"] == 1
    assert summary["truncated"] is False
    # posture aggregate: each costed part's make-now estimate has 1 DEFAULT + 1
    # SHOP driver → 3 costed parts = 3 default + 3 shop.
    p = summary["posture"]
    assert p["default"] == 3 and p["shop"] == 3
    assert p["measured"] == 0 and p["user"] == 0
    assert p["total"] == 6 and p["grounded"] == 3
    assert p["grounded_pct"] == 0.5


@pytest.mark.asyncio
async def test_build_portfolio_truncated_propagates(monkeypatch):
    # Shrink the scan cap so 2 distinct cost rows exceed it → truncated True.
    monkeypatch.setattr(svc, "CATALOG_SCAN_CAP", 1)
    c1 = _Row("m1", _cost_json(alt=None), ulid="ul-b")
    c2 = _Row("m2", _cost_json(alt=None), ulid="ul-a")
    session = _FakeSession(analyses=[], costs=[c1, c2])
    out = await svc.build_portfolio(session, org_id="org-1")
    assert out["summary"]["truncated"] is True


@pytest.mark.asyncio
async def test_build_portfolio_empty_org_is_empty_not_error():
    out = await svc.build_portfolio(_FakeSession([], []), org_id=None)
    assert out["rows"] == []
    assert out["summary"]["parts"] == 0
    assert out["summary"]["posture"]["total"] == 0
    assert out["summary"]["truncated"] is False

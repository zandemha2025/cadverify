"""Pure-derivation tests for the catalog service (W1 step 4).

No DB, no I/O — these exercise the row-derivation heart directly with plain
dicts (the same shapes the engine's ``report_to_dict`` / analysis
``result_json`` produce). They pin the honesty contract: findings are
route-scoped, prices are withheld on blocked routes, and a part with no analysis
reports ``findings: null`` rather than a fabricated zero. Runs in every pytest
invocation (no Postgres required).
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.services import catalog_service as svc
from src.services.catalog_service import SourceRef

# ---------------------------------------------------------------------------
# Fixtures — minimal but real result_json shapes
# ---------------------------------------------------------------------------


def _analysis_json(best="cnc_3axis"):
    """An analysis result_json with a universal issue + on-route + off-route
    process issues, so scoping is observable."""
    return {
        "overall_verdict": "issues",
        "best_process": best,
        "universal_issues": [
            {"code": "NON_WATERTIGHT", "severity": "error", "message": "not watertight"},
        ],
        "process_scores": [
            {
                "process": "cnc_3axis",
                "score": 0.9,
                "verdict": "pass",
                "recommended_material": "aluminum_6061",
                "issues": [
                    {"code": "DEEP_POCKET", "severity": "warning", "message": "deep pocket"},
                    {"code": "SMALL_HOLE", "severity": "info", "message": "small hole"},
                ],
            },
            {
                # An off-route process (a casting process that always fails on a
                # printed/milled part) — its issues must NOT inflate the headline.
                "process": "die_casting",
                "score": 0.1,
                "verdict": "fail",
                "recommended_material": "zamak",
                "issues": [
                    {"code": "NO_DRAFT", "severity": "error", "message": "no draft"},
                    {"code": "UNDERCUT", "severity": "error", "message": "undercut"},
                ],
            },
        ],
    }


def _cost_json(*, process="cnc_3axis", dfm_ready=True, blockers=None, drivers=None,
               validated=False, unit=12.5, qty=50):
    return {
        "decision": {
            "make_now_process": process,
            "make_now_material": "aluminum_6061",
            "crossover_qty": 500.0,
            "recommendation": {},
        },
        "estimates": [
            {
                "process": process,
                "material": "aluminum_6061",
                "quantity": qty,
                "unit_cost_usd": unit,
                "dfm_ready": dfm_ready,
                "dfm_blockers": blockers or [],
                "confidence": {"validated": validated, "label": "assumption band"},
                "drivers": drivers
                if drivers is not None
                else [
                    {"name": "machine_rate", "provenance": "DEFAULT", "source": "generic"},
                    {"name": "labor_rate", "provenance": "SHOP", "source": "your shop"},
                ],
            },
            {
                # a second estimate on a different process — should be ignored by
                # make_now_estimate (only make_now_process matches)
                "process": "injection_molding",
                "material": "abs",
                "quantity": qty,
                "unit_cost_usd": 3.0,
                "dfm_ready": False,
                "dfm_blockers": ["needs tooling"],
                "confidence": {"validated": False},
                "drivers": [],
            },
        ],
    }


def _ref(result_json, *, id="01ABC", fn="part.stl", ft="stl", ts=None):
    return SourceRef(
        id=id,
        filename=fn,
        file_type=ft,
        created_at=ts or datetime(2026, 6, 1, tzinfo=timezone.utc),
        result_json=result_json,
    )


# ---------------------------------------------------------------------------
# Severity buckets + finding scoping
# ---------------------------------------------------------------------------


def test_severity_bucket_matches_frontend():
    assert svc.issue_severity_bucket("error") == "critical"
    assert svc.issue_severity_bucket("critical") == "critical"
    assert svc.issue_severity_bucket("fail") == "critical"
    assert svc.issue_severity_bucket("warning") == "advisory"
    assert svc.issue_severity_bucket("warn") == "advisory"
    assert svc.issue_severity_bucket("info") == "info"
    assert svc.issue_severity_bucket("") == "info"


def test_scoped_findings_counts_only_route_plus_universal():
    """The route (cnc_3axis) + universal issues count; the off-route die_casting
    issues do NOT inflate the headline (the FRAGILE-1 fix)."""
    counts = svc.scoped_findings(_analysis_json(), ["cnc_3axis"])
    # universal NON_WATERTIGHT (critical) + DEEP_POCKET (advisory) + SMALL_HOLE (info)
    assert counts == {"total": 3, "critical": 1, "advisory": 1, "info": 1}


def test_scoped_findings_empty_scope_counts_only_universal():
    counts = svc.scoped_findings(_analysis_json(), [])
    assert counts == {"total": 1, "critical": 1, "advisory": 0, "info": 0}


def test_scoped_findings_dedup_by_code_message():
    """Same (code, message) on universal + a scoped process collapses to one,
    keeping the first (universal) severity."""
    aj = {
        "universal_issues": [
            {"code": "X", "severity": "error", "message": "dup"},
        ],
        "process_scores": [
            {"process": "cnc_3axis", "issues": [
                {"code": "X", "severity": "info", "message": "dup"},
            ]},
        ],
    }
    counts = svc.scoped_findings(aj, ["cnc_3axis"])
    assert counts == {"total": 1, "critical": 1, "advisory": 0, "info": 0}


# ---------------------------------------------------------------------------
# Posture
# ---------------------------------------------------------------------------


def test_posture_mix_and_grounded_pct():
    drivers = [
        {"provenance": "MEASURED"},
        {"provenance": "SHOP"},
        {"provenance": "USER"},
        {"provenance": "DEFAULT"},
    ]
    p = svc.posture(drivers)
    assert p["measured"] == 1 and p["shop"] == 1 and p["user"] == 1 and p["default"] == 1
    assert p["total"] == 4 and p["grounded"] == 3 and p["guess"] == 1
    assert p["grounded_pct"] == 0.75


def test_posture_empty_is_zero_not_nan():
    p = svc.posture([])
    assert p["total"] == 0 and p["grounded_pct"] == 0.0
    p2 = svc.posture(None)
    assert p2["total"] == 0 and p2["grounded_pct"] == 0.0


# ---------------------------------------------------------------------------
# make_now_estimate
# ---------------------------------------------------------------------------


def test_make_now_estimate_picks_route_process():
    est = svc.make_now_estimate(_cost_json(process="cnc_3axis"))
    assert est is not None and est["process"] == "cnc_3axis"


def test_make_now_estimate_none_when_no_match():
    j = _cost_json(process="cnc_3axis")
    j["decision"]["make_now_process"] = "sheet_metal"  # no matching estimate
    assert svc.make_now_estimate(j) is None
    # and none when no decision at all
    assert svc.make_now_estimate({"estimates": []}) is None


# ---------------------------------------------------------------------------
# derive_row — the integration of the pure pieces
# ---------------------------------------------------------------------------


def test_derive_row_costed_with_analysis_full_shape():
    row = svc.derive_row(
        part_key="mesh1",
        analysis=_ref(_analysis_json(), id="AN1"),
        cost=_ref(_cost_json(), id="CD1"),
    )
    assert row["part_key"] == "mesh1"
    assert row["lifecycle_state"] == "Costed"
    assert row["recommended_route"] == {
        "process": "cnc_3axis",
        "material": "aluminum_6061",
        "source": "costed",
    }
    # unit cost present, not withheld
    assert row["unit_cost"]["usd"] == 12.5
    assert row["unit_cost"]["qty"] == 50
    assert row["unit_cost"]["withheld"] is False
    assert row["unit_cost"]["validated"] is False  # honest: no ground truth yet
    # findings route-scoped (from the analysis)
    assert row["findings"]["total"] == 3
    assert row["findings"]["scoped_process"] == "cnc_3axis"
    # posture from the make-now estimate's drivers (1 DEFAULT + 1 SHOP)
    assert row["provenance_posture"]["total"] == 2
    assert row["provenance_posture"]["grounded"] == 1
    # links to both artifacts
    assert row["cost_decision"] == {"id": "CD1", "url": "/api/v1/cost-decisions/CD1"}
    assert row["analysis"] == {"id": "AN1", "url": "/api/v1/analyses/AN1"}


def test_derive_row_blocked_route_withholds_price():
    row = svc.derive_row(
        part_key="mesh2",
        analysis=None,
        cost=_ref(
            _cost_json(dfm_ready=False, blockers=["Wall too thin for CNC."]),
            id="CD2",
        ),
    )
    assert row["unit_cost"]["usd"] is None
    assert row["unit_cost"]["withheld"] is True
    assert row["unit_cost"]["withheld_reason"] == "Wall too thin for CNC."
    assert row["route_blocker_count"] == 1
    # no analysis → findings honestly absent (NOT a fabricated zero)
    assert row["findings"] is None


def test_derive_row_drafted_only_analysis():
    row = svc.derive_row(
        part_key="mesh3",
        analysis=_ref(_analysis_json(best="cnc_3axis"), id="AN3"),
        cost=None,
    )
    assert row["lifecycle_state"] == "Drafted"
    # route from the DFM best_process, honestly labeled source="dfm"
    assert row["recommended_route"]["process"] == "cnc_3axis"
    assert row["recommended_route"]["source"] == "dfm"
    assert row["recommended_route"]["material"] == "aluminum_6061"
    # no cost → no price, no posture
    assert row["unit_cost"] is None
    assert row["provenance_posture"] is None
    # findings scoped to the DFM route
    assert row["findings"]["total"] == 3
    assert row["cost_decision"] is None
    assert row["analysis"]["id"] == "AN3"


def test_derive_row_costed_no_analysis_findings_null():
    """Costed but never DFM-validated: route/price/posture real; findings null
    (a cost decision does NOT embed the DFM Issue array — honest absence)."""
    row = svc.derive_row(
        part_key="mesh4", analysis=None, cost=_ref(_cost_json(), id="CD4")
    )
    assert row["lifecycle_state"] == "Costed"
    assert row["unit_cost"]["usd"] == 12.5
    assert row["findings"] is None


def test_derive_row_updated_at_is_latest_activity():
    early = datetime(2026, 1, 1, tzinfo=timezone.utc)
    late = datetime(2026, 6, 15, tzinfo=timezone.utc)
    row = svc.derive_row(
        part_key="mesh5",
        analysis=_ref(_analysis_json(), id="AN5", ts=early),
        cost=_ref(_cost_json(), id="CD5", ts=late),
    )
    assert row["updated_at"] == late.isoformat()


def test_derive_row_filename_prefers_cost_decision():
    """The cost decision is the headline 'decision' artifact — its filename wins
    when both exist."""
    row = svc.derive_row(
        part_key="mesh6",
        analysis=_ref(_analysis_json(), id="AN6", fn="analysis-name.stl"),
        cost=_ref(_cost_json(), id="CD6", fn="cost-name.stl"),
    )
    assert row["filename"] == "cost-name.stl"


# ---------------------------------------------------------------------------
# Filters + facets (real predicates over derived rows)
# ---------------------------------------------------------------------------


def _rows():
    costed = svc.derive_row(
        part_key="m-costed",
        analysis=_ref(_analysis_json(), id="ANc"),
        cost=_ref(_cost_json(), id="CDc"),
    )
    drafted = svc.derive_row(
        part_key="m-drafted", analysis=_ref(_analysis_json(), id="ANd"), cost=None
    )
    costed_no_findings = svc.derive_row(
        part_key="m-clean",
        analysis=_ref(
            {"best_process": "cnc_3axis", "universal_issues": [], "process_scores": []},
            id="ANk",
        ),
        cost=_ref(_cost_json(), id="CDk"),
    )
    costed_unknown = svc.derive_row(
        part_key="m-unknown", analysis=None, cost=_ref(_cost_json(), id="CDu")
    )
    return [costed, drafted, costed_no_findings, costed_unknown]


def test_matches_filters_state():
    rows = _rows()
    costed = [r for r in rows if svc.matches_filters(r, state="Costed", route=None, has_findings=None)]
    assert {r["part_key"] for r in costed} == {"m-costed", "m-clean", "m-unknown"}
    drafted = [r for r in rows if svc.matches_filters(r, state="Drafted", route=None, has_findings=None)]
    assert {r["part_key"] for r in drafted} == {"m-drafted"}


def test_matches_filters_route():
    rows = _rows()
    hit = [r for r in rows if svc.matches_filters(r, state=None, route="cnc_3axis", has_findings=None)]
    assert len(hit) == 4  # all four route to cnc_3axis
    miss = [r for r in rows if svc.matches_filters(r, state=None, route="sheet_metal", has_findings=None)]
    assert miss == []


def test_matches_filters_has_findings_tri_state():
    rows = _rows()
    # has_findings=true → only rows with >0 route-scoped findings
    yes = [r for r in rows if svc.matches_filters(r, state=None, route=None, has_findings=True)]
    assert {r["part_key"] for r in yes} == {"m-costed", "m-drafted"}
    # has_findings=false → known-zero only (m-clean); NOT the unknown (no analysis)
    no = [r for r in rows if svc.matches_filters(r, state=None, route=None, has_findings=False)]
    assert {r["part_key"] for r in no} == {"m-clean"}
    # the unknown row (no analysis) matches NEITHER true nor false
    unknown_row = next(r for r in rows if r["part_key"] == "m-unknown")
    assert svc.row_has_findings(unknown_row) is None


def test_compute_facets_counts():
    facets = svc.compute_facets(_rows())
    assert facets["state"] == {"Costed": 3, "Drafted": 1}
    assert facets["route"]["cnc_3axis"] == 4
    assert facets["findings"] == {
        "with_findings": 2,
        "without_findings": 1,
        "unknown": 1,
    }

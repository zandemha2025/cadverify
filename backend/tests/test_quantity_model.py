"""The price at any quantity is the model's own (ce-06, ce-15).

Each estimate's ``qty_model`` must give, at every other quantity, the unit cost the
engine computes there: for every process, with per-plate setups, learning, order
minimums, tooling, a declared tolerance, a region, overhead and margin, an owned
machine and declared finishes. Then the cost engineer's pocket block: the model's
price at 25 from the record priced at 1 and 100 is her $40.10, where the straight
line between $149.30 and $36.69 read $55.98.
"""

from __future__ import annotations

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult, ProcessType as PT
from src.analysis.processes import base as pbase
from src.analysis.processes.base import get_analyzer
from src.matcher.profile_matcher import rank_processes, score_process
import src.analysis.processes  # noqa: F401  populate registry

from src.costing import EstimateOptions, estimate_decision
from src.costing import cost_model
from src.costing.cost_model import cost_breakdown
from src.costing.quantity_model import model_at, unit_cost_at
from src.costing.rates import build_rate_card
from src.costing.routing import select_material

from tests.test_cost_engineer_pocket_block import CYCLE_HR, _pocket_block

QTYS = [1, 7, 25, 100, 250, 1000, 2500, 10000]


def _analyze(mesh):
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
              for p in pbase._REGISTRY if get_analyzer(p)]
    result = AnalysisResult(filename="qm.stl", file_type="stl", geometry=geometry,
                            segments=ctx.segments, universal_issues=run_universal_checks(mesh),
                            process_scores=scores)
    rank_processes(result)
    return result, mesh, ctx.features


def _check_report(report, label):
    by_proc: dict = {}
    for e in report.estimates:
        by_proc.setdefault((e["process"], e["material"]), {})[e["quantity"]] = e
    assert by_proc, f"{label}: nothing priced"
    checked = 0
    for (proc, mat), at in by_proc.items():
        for q0, e0 in at.items():
            assert isinstance(e0.get("qty_model"), dict), f"{label} {proc}@{q0}: no qty_model"
            for q1, e1 in at.items():
                got = unit_cost_at(e0, q1)
                want = e1["unit_cost_usd"]
                assert got == pytest.approx(want, abs=0.0051 + 1e-4 * want), (
                    f"{label} {proc}/{mat}: model from {q0} says ${got:.4f} at {q1}, engine ${want}")
                checked += 1
    return {p for p, _m in by_proc}, checked


@pytest.mark.parametrize("label,mesh,opts", [
    ("block-aluminum", trimesh.creation.box(extents=[40.0, 30.0, 25.0]), {"material_class": "aluminum"}),
    ("block-polymer", trimesh.creation.box(extents=[40.0, 30.0, 25.0]), {"material_class": "polymer"}),
    ("small-polymer", trimesh.creation.box(extents=[12.0, 10.0, 6.0]), {"material_class": "polymer"}),
    ("shaft-steel", trimesh.creation.cylinder(radius=12.0, height=90.0, sections=96), {"material_class": "steel"}),
    ("plate-steel", trimesh.creation.box(extents=[120.0, 80.0, 2.0]), {"material_class": "steel"}),
    ("block-steel-tight-CN-overhead", trimesh.creation.box(extents=[60.0, 40.0, 20.0]),
     {"material_class": "steel", "tolerance_class": "tight", "region": "CN", "region_is_user": True,
      "rate_overrides": {"overhead": 0.15, "margin": 0.1}}),
    ("block-aluminum-owned-specs", trimesh.creation.box(extents=[60.0, 40.0, 20.0]),
     {"material_class": "aluminum", "owned_processes": frozenset({PT.CNC_3AXIS}),
      "part_specs": {"finishes": ["bead_blast", "anodize_ii"], "heat_treatments": ["stress_relief"],
                     "inspection": ["fai_as9102", "full_100"]}}),
])
def test_qty_model_reproduces_the_engine_at_every_quantity(label, mesh, opts):
    result, mesh, feats = _analyze(mesh)
    report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=QTYS, **opts))
    procs, checked = _check_report(report, label)
    assert checked >= len(QTYS) ** 2


def test_every_family_is_covered():
    """The parametrized parts between them price every family the model sorts lines for."""
    seen: set = set()
    for mesh, cls in ((trimesh.creation.box(extents=[40.0, 30.0, 25.0]), "aluminum"),
                      (trimesh.creation.box(extents=[40.0, 30.0, 25.0]), "polymer"),
                      (trimesh.creation.box(extents=[120.0, 80.0, 2.0]), "steel"),
                      (trimesh.creation.box(extents=[40.0, 30.0, 25.0]), "steel"),
                      (trimesh.creation.box(extents=[40.0, 30.0, 25.0]), "stainless"),
                      (trimesh.creation.cylinder(radius=12.0, height=90.0, sections=96), "steel"),
                      (trimesh.creation.box(extents=[300.0, 200.0, 150.0]), "titanium")):
        result, mesh, feats = _analyze(mesh)
        report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[10, 1000], material_class=cls))
        seen |= _check_report(report, cls)[0]
    for p in ("cnc_3axis", "cnc_5axis", "fdm", "sla", "sls", "mjf", "injection_molding", "sand_casting",
              "investment_casting", "forging", "wire_edm", "sheet_metal", "dmls", "binder_jetting", "die_casting",
              "cnc_turning", "waam"):
        assert p in seen, f"{p} not priced by these parts: {sorted(seen)}"


# ── her pocket block ──────────────────────────────────────────────────────────

@pytest.fixture()
def block(monkeypatch):
    monkeypatch.setattr(cost_model, "_cnc_cycle",
                        lambda process, drivers, cls, rates: (CYCLE_HR, 0.1782, "her cycle"))
    rates = build_rate_card()
    mat = select_material(PT.CNC_3AXIS, "steel", rates)
    return lambda q: cost_breakdown(PT.CNC_3AXIS, _pocket_block(), mat, "steel", q, rates, "US")


def test_her_25_from_the_record_at_1_and_100(block):
    """ce-06: model at 25 = material 0.52 + machine 15.69 + labor 17.50 + tools 0.78
    + setup 26.25/25 = 1.05 + programming 70/25 = 2.80 + inspection (0.5/25 + 0.03) × 35 = 1.75
    = $40.10. The record priced 1 and 100 ($149.30, $36.69); a straight line between
    them on the log-log chart read $55.98 (+40%)."""
    for q0 in (1, 100):
        m = block(q0).qty_model
        assert round(model_at(m, 25), 2) == 40.10
    # and it is what pricing 25 gives (her "Price 25": $40.10)
    assert round(block(25).unit_cost_usd, 2) == 40.10


@pytest.mark.parametrize("q", [25, 250, 2500])
def test_her_quick_values_are_the_model(block, q):
    """The quick value at 25, 250 and 2,500 is within 2% of the model: here, the same number."""
    quick = model_at(block(100).qty_model, q)
    priced = block(q).unit_cost_usd
    assert abs(quick - priced) <= 0.02 * priced
    assert quick == pytest.approx(priced, abs=0.0002)


def test_calibration_moves_the_model_like_the_record():
    """A record calibrated from actuals: machine × hours factor, then the whole × cost factor."""
    e = {"qty_model": {"v": 1, "once_usd": 100.0, "per_part_usd": 5.0, "machine_usd": 10.0,
                       "learning_usd": 0.0, "learning": None, "per_plate": [], "order_min_usd": 0.0,
                       "specs": []},
         "calibration": {"hours_factor": 1.2, "cost_factor": 0.9}}
    # (100/10 + 5 + 10 + 10 × 0.2) × 0.9 = 24.3
    assert unit_cost_at(e, 10) == pytest.approx(24.3)
    assert unit_cost_at({"line_items": {}}, 10) is None        # priced before the model was kept
    assert unit_cost_at(e, 0) is None

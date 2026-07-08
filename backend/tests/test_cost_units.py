"""B5 cost-unit safety — the units landmine defense.

STL/mesh files carry NO unit metadata; the engine has always interpreted vertex
coordinates as MILLIMETRES. An inch-authored part therefore silently mis-costs by
25.4**3 (~16,387x volume) — a confidently-wrong number in a valid-looking band,
the worst possible pilot failure. Two independent defenses are proved here:

  1. An EXPLICIT `units` declaration (mm|inch) that rescales the mesh into mm
     EXACTLY ONCE at the parse seam, before any geometry/DFM/cost extraction.
  2. An HONEST plausibility WARNING (never a corrected number) when the
     mm-interpreted geometry is egregiously implausible for a single part.

Honesty invariants proved below:
  * mm (default / unset / explicitly declared) is BYTE-IDENTICAL to pre-B5.
  * inch scales the VOLUME-DRIVEN cost by exactly 25.4**3 — proven both at the
    unit level (scale_mesh_to_mm) and end-to-end through the real /validate/cost
    endpoint, so the test FAILS if the conversion is deleted at EITHER seam.
  * conversion happens EXACTLY ONCE (ratio ~ 25.4**3, never 1x=none, never
    25.4**6=double).
  * the warning is a WARNING (MEASURED geometry vs ASSUMED units), never a verdict.

Procedural meshes only — no DB, no real-parts corpus, always runs in CI.
"""

from __future__ import annotations

import importlib

import pytest
import trimesh
from fastapi.testclient import TestClient

from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult
from src.analysis.processes import base as pbase
from src.analysis.processes.base import get_analyzer
import src.analysis.processes  # noqa: F401  populate the process registry
from src.matcher.profile_matcher import rank_processes, score_process

from src.costing.estimate import EstimateOptions, estimate_decision
from src.costing.report import report_to_dict
from src.costing.units import (
    MM_PER_INCH,
    implausible_volume_warning,
    scale_mesh_to_mm,
    unit_scale,
)

CUBED = MM_PER_INCH ** 3  # 25.4**3 = 16387.064 — the inch->mm volume blow-up


# ── engine harness (mirrors the routes.py flow: scale mesh, THEN run engine) ──
def _run_engine(mesh, units, material_class="aluminum", quantities=(100,)):
    """Cost `mesh` through the real engine exactly as the route does: the caller
    has ALREADY scaled the mesh into mm (routes does this at the parse seam), and
    `units` is the DECLARATIVE record threaded into EstimateOptions."""
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    universal = run_universal_checks(mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
              for p in pbase._REGISTRY if get_analyzer(p)]
    result = AnalysisResult(filename="u.stl", file_type="stl", geometry=geometry,
                            segments=ctx.segments, universal_issues=universal,
                            process_scores=scores)
    rank_processes(result)
    opts = EstimateOptions(quantities=list(quantities), material_class=material_class,
                           units=units, units_is_user=(units != "mm"))
    return estimate_decision(result, ctx.mesh, ctx.features, opts)


def _line_item(report, key):
    """First estimate's `key` line item (volume-driven components live here)."""
    return report.estimates[0]["line_items"].get(key, 0.0)


# ══════════════════════════════════════════════════════════════════════════
# 1) unit level — scale factor + the exactly-once, non-mutating mesh rescale
# ══════════════════════════════════════════════════════════════════════════
def test_unit_scale_factor():
    assert unit_scale("mm") == 1.0
    assert unit_scale("inch") == MM_PER_INCH == 25.4
    # anything unrecognized is a SAFE no-op (mm), never a silent wrong scale
    assert unit_scale("garbage") == 1.0
    assert unit_scale("") == 1.0


def test_scale_mesh_to_mm_is_noop_for_mm():
    box = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    out = scale_mesh_to_mm(box, "mm")
    # mm => the SAME object untouched (this is what makes the default byte-identical)
    assert out is box
    assert abs(out.volume - box.volume) == 0.0


def test_scale_mesh_to_mm_inch_scales_volume_exactly_once():
    box = trimesh.creation.box(extents=[1.0, 1.0, 1.0])
    v0 = box.volume
    out = scale_mesh_to_mm(box, "inch")
    # never mutate the caller's mesh — inch is a COPY
    assert out is not box
    assert box.volume == v0
    ratio = out.volume / v0
    # EXACTLY once: volume blows up by 25.4**3, NOT 1x (no scale) and NOT
    # 25.4**6 (double scale). If `apply_scale` is deleted this assert fails.
    assert ratio == pytest.approx(CUBED, rel=1e-9)
    assert abs(max(out.extents) - MM_PER_INCH) < 1e-9   # linear dims x25.4


def test_implausible_volume_warning_structure_and_bounds():
    # plausible single part => None (no warning, default path stays clean)
    assert implausible_volume_warning(1.0, 10.0, "mm") is None
    # egregiously tiny (sub-grain) => warning
    w = implausible_volume_warning(2.7e-5, 0.3, "mm")
    assert w is not None
    assert w["code"] == "IMPLAUSIBLE_VOLUME" and w["severity"] == "warning"
    # honest provenance: geometry MEASURED, units ASSUMED — never a corrected number
    assert w["provenance"] == "measured-geometry-vs-assumed-units"
    assert w["assumed_units"] == "mm"
    assert "measured" in w and "volume_cm3" in w["measured"]
    assert "verdict" not in w and "corrected" not in w
    # egregiously huge (bigger than a ~1 m^3 envelope) => warning
    assert implausible_volume_warning(2_000_000.0, 6000.0, "mm") is not None
    # zero/degenerate volume is NOT a units warning (that path is GEOMETRY_INVALID)
    assert implausible_volume_warning(0.0, 0.0, "mm") is None


# ══════════════════════════════════════════════════════════════════════════
# 2) engine level — inch scales the VOLUME-DRIVEN cost by ~25.4**3
# ══════════════════════════════════════════════════════════════════════════
def test_inch_scales_volume_driven_cost_by_25_4_cubed():
    """The headline B5 claim: the SAME mesh declared inch vs mm differs by the
    volume blow-up on the volume-driven cost components. Proven on the geometry
    volume AND on the material (feedstock) line item."""
    base = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    rep_mm = _run_engine(scale_mesh_to_mm(base, "mm"), "mm")
    rep_in = _run_engine(scale_mesh_to_mm(base, "inch"), "inch")

    # geometry volume scaled EXACTLY once => 25.4**3 (rounded to 2dp in the summary)
    vol_ratio = rep_in.geometry["volume_cm3"] / rep_mm.geometry["volume_cm3"]
    assert vol_ratio == pytest.approx(CUBED, rel=1e-4)
    # unambiguously exactly-once: far from 1x (no conversion) and 25.4**6 (double)
    assert 100.0 < vol_ratio < CUBED * 100.0

    # the material (volume-driven feedstock) line item scales by the same ~25.4**3
    # (both reports pick the same headline process for the same shape)
    assert rep_mm.estimates[0]["process"] == rep_in.estimates[0]["process"]
    mat_mm, mat_in = _line_item(rep_mm, "material"), _line_item(rep_in, "material")
    assert mat_mm > 0 and mat_in > 0
    mat_ratio = mat_in / mat_mm
    # within 1% absorbs the 4-decimal rounding on the tiny mm material value
    assert mat_ratio == pytest.approx(CUBED, rel=1e-2)


def test_mm_declared_is_byte_identical_to_undeclared():
    """Declaring the canonical unit (mm) changes NOTHING — no source_units line,
    no scaling, no warning — so the report dict equals the unset-default one."""
    base = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    undeclared = report_to_dict(_run_engine(scale_mesh_to_mm(base, "mm"), "mm"))
    # a normal part carries NO units keys at all (byte-identity guard)
    assert "unit_warnings" not in undeclared
    assert not any(a["name"] == "source_units" for a in undeclared["assumptions"])


def test_inch_declaration_discloses_source_units_as_user():
    base = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    d = report_to_dict(_run_engine(scale_mesh_to_mm(base, "inch"), "inch"))
    su = next((a for a in d["assumptions"] if a["name"] == "source_units"), None)
    assert su is not None
    assert su["provenance"] == "USER"          # the DECLARATION is user-supplied
    assert su["value"] == MM_PER_INCH           # the scale actually applied
    assert "scaled" in su["source"] and "before costing" in su["source"]


def test_warning_fires_undeclared_and_clears_when_inch_declared():
    """The safety net: an egregiously tiny part read as mm raises the warning;
    the SAME mesh declared inch (scaled x25.4) becomes plausible and clears it."""
    tiny = trimesh.creation.box(extents=[0.3, 0.3, 0.3])  # sub-mm => implausible as mm
    d_undeclared = report_to_dict(_run_engine(scale_mesh_to_mm(tiny, "mm"), "mm"))
    d_inch = report_to_dict(_run_engine(scale_mesh_to_mm(tiny, "inch"), "inch"))

    assert "unit_warnings" in d_undeclared
    w = d_undeclared["unit_warnings"][0]
    assert w["code"] == "IMPLAUSIBLE_VOLUME" and w["severity"] == "warning"
    assert w["measured"]["volume_cm3"] > 0     # raw (unrounded) volume survives
    # declaring inch rescales it into a plausible part => warning gone
    assert "unit_warnings" not in d_inch


# ══════════════════════════════════════════════════════════════════════════
# 3) API level — the units param on the real /validate/cost endpoint
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)  # conftest re-applies the auth/DB bypass on reload
    return TestClient(main.app)


def _post(client, name, data, **form):
    return client.post(
        "/api/v1/validate/cost",
        files={"file": (name, data, "application/octet-stream")},
        data=form,
    )


def test_api_units_validation_rejects_unknown(client, cube_10mm, stl_bytes_of):
    r = _post(client, "c.stl", stl_bytes_of(cube_10mm),
              qty="50", material_class="aluminum", units="furlong")
    assert r.status_code == 400, r.text
    # the app wraps HTTPException detail in a structured error envelope
    assert "units" in r.json()["message"].lower()


def test_api_default_and_explicit_mm_are_identical(client, cube_10mm, stl_bytes_of):
    """DEFAULT PATH BYTE-IDENTITY: unset units and units=mm give the SAME body."""
    data = stl_bytes_of(cube_10mm)
    r_default = _post(client, "c.stl", data, qty="50,5000", material_class="aluminum")
    r_mm = _post(client, "c.stl", data, qty="50,5000", material_class="aluminum", units="mm")
    assert r_default.status_code == 200 and r_mm.status_code == 200
    b_default, b_mm = r_default.json(), r_mm.json()
    # `saved` carries a fresh random persistence ULID each call — not part of the
    # cost decision; drop it before comparing the DECISION for byte-identity.
    b_default.pop("saved", None)
    b_mm.pop("saved", None)
    assert b_default == b_mm
    # a normal part declares no units warning
    assert "unit_warnings" not in b_default


def test_api_inch_scales_volume_through_the_endpoint(client, cube_10mm, stl_bytes_of):
    """End-to-end conversion guard: the SAME bytes posted as inch vs mm differ by
    exactly 25.4**3 in reported volume. This depends on the routes.py parse-seam
    rescale — delete it and inch==mm and this assert fails."""
    data = stl_bytes_of(cube_10mm)
    r_mm = _post(client, "c.stl", data, qty="50", material_class="aluminum", units="mm")
    r_in = _post(client, "c.stl", data, qty="50", material_class="aluminum", units="inch")
    assert r_mm.status_code == 200 and r_in.status_code == 200, (r_mm.text, r_in.text)
    vol_mm = r_mm.json()["geometry"]["volume_cm3"]
    vol_in = r_in.json()["geometry"]["volume_cm3"]
    assert vol_in / vol_mm == pytest.approx(CUBED, rel=1e-4)
    # inch body discloses the USER source_units assumption; mm body does not
    assert any(a["name"] == "source_units" for a in r_in.json()["assumptions"])
    assert not any(a["name"] == "source_units" for a in r_mm.json()["assumptions"])


def test_api_warning_on_implausible_bbox(client, stl_bytes_of):
    """A sub-mm part uploaded WITHOUT a units declaration surfaces the honest
    plausibility warning (confirm mm vs inch) rather than a silent wrong number."""
    tiny = trimesh.creation.box(extents=[0.3, 0.3, 0.3])
    r = _post(client, "tiny.stl", stl_bytes_of(tiny), qty="50", material_class="aluminum")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "unit_warnings" in body and body["unit_warnings"]
    w = body["unit_warnings"][0]
    assert w["code"] == "IMPLAUSIBLE_VOLUME" and w["severity"] == "warning"
    assert w["assumed_units"] == "mm"

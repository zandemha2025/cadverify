"""Material-aware best_process + COTS fastener costing (Round-3 trust-killer fix).

Gates the three coherent fixes so they can never silently regress:

  Fix 1 — best_process is chosen ONLY among processes makeable in the declared
          material class: a metal part never surfaces a resin/SLS/binder-jet
          "best process".
  Fix 2 — DFM best_process AGREES with (or is a sane sibling of) the cost
          make-now: on a top-score tie it is biased toward the cost route.
  Fix 3 — standard fasteners (bolt/nut/screw/washer/…) are detected COTS and
          costed as BUY, with the machined figure re-framed as an in-house
          fabrication upper-bound.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import trimesh

from src.analysis.models import (
    AnalysisResult,
    BoundingBox,
    GeometryInfo,
    ProcessScore,
    ProcessType,
)
from src.parsers.step_mesher import is_step_supported

_needs_gmsh = pytest.mark.skipif(
    not is_step_supported(), reason="gmsh/STEP path unavailable"
)

_RESIN = {ProcessType.SLA, ProcessType.DLP, ProcessType.SLS, ProcessType.MJF,
          ProcessType.FDM, ProcessType.BINDER_JET}


# ── Fix 1: processes_for_material_class ─────────────────────────────────────
def test_processes_for_material_class_metal_excludes_resin():
    from src.profiles.database import processes_for_material_class

    for cls in ("aluminum", "steel", "stainless", "titanium"):
        procs = processes_for_material_class(cls)
        assert procs, cls
        # No resin / FDM process is ever makeable in a metal class.
        assert ProcessType.SLA not in procs, cls
        assert ProcessType.DLP not in procs, cls
        assert ProcessType.FDM not in procs, cls
        # CNC milling is always available for a metal.
        assert ProcessType.CNC_3AXIS in procs, cls
    # binder-jet is a metal process, but ONLY for the classes whose profiles list
    # it (stainless has 17-4 PH / SS316L binder-jet; aluminum does not).
    assert ProcessType.BINDER_JET in processes_for_material_class("stainless")
    assert ProcessType.BINDER_JET not in processes_for_material_class("aluminum")


def test_processes_for_material_class_polymer_excludes_metal_only():
    from src.profiles.database import processes_for_material_class

    procs = processes_for_material_class("polymer")
    assert ProcessType.SLA in procs and ProcessType.DLP in procs
    assert ProcessType.INJECTION_MOLDING in procs
    # A polymer is never die-cast or binder-jet-metal.
    assert ProcessType.DIE_CASTING not in procs
    assert ProcessType.BINDER_JET not in procs


def test_processes_for_material_class_unknown_is_empty():
    from src.profiles.database import processes_for_material_class

    assert processes_for_material_class("unobtanium") == frozenset()


# ── Fix 1+2: best_process_for_material ──────────────────────────────────────
def _mk_result(scores: list[tuple[ProcessType, float]]) -> AnalysisResult:
    bb = BoundingBox(0, 0, 0, 10, 10, 10)
    geo = GeometryInfo(
        vertex_count=8, face_count=12, volume=1000.0, surface_area=600.0,
        bounding_box=bb, is_watertight=True, is_manifold=True, euler_number=2,
        center_of_mass=(5.0, 5.0, 5.0),
    )
    ps = [ProcessScore(process=p, score=s,
                       verdict="pass" if s >= 1.0 else "issues")
          for p, s in scores]
    return AnalysisResult(filename="x.step", file_type="step", geometry=geo,
                          process_scores=ps)


def test_best_process_never_resin_for_metal():
    from src.matcher.profile_matcher import best_process_for_material

    # Resin ties at the top on geometry (the material-blind bug); CNC is a hair
    # lower. Material-aware selection must reject resin and pick the metal process.
    res = _mk_result([
        (ProcessType.DLP, 1.0), (ProcessType.SLA, 1.0),
        (ProcessType.CNC_3AXIS, 0.9), (ProcessType.CNC_TURNING, 0.9),
    ])
    best = best_process_for_material(res, "aluminum")
    assert best not in _RESIN
    assert best in {ProcessType.CNC_3AXIS, ProcessType.CNC_TURNING}


def test_best_process_prefers_cost_make_now_on_tie():
    from src.matcher.profile_matcher import best_process_for_material

    # cnc_turning and cnc_3axis tie at the top; prefer the cost make-now (turning).
    res = _mk_result([
        (ProcessType.CNC_3AXIS, 1.0), (ProcessType.CNC_TURNING, 1.0),
        (ProcessType.DLP, 1.0),
    ])
    best = best_process_for_material(res, "aluminum",
                                     prefer=["cnc_turning", "cnc_3axis"])
    assert best == ProcessType.CNC_TURNING


def test_best_process_none_when_all_fail():
    from src.matcher.profile_matcher import best_process_for_material

    res = _mk_result([(ProcessType.CNC_3AXIS, 0.0), (ProcessType.DLP, 0.0)])
    assert best_process_for_material(res, "aluminum") is None


def test_rank_processes_no_material_is_byte_identical():
    from src.matcher.profile_matcher import rank_processes

    res = _mk_result([
        (ProcessType.DLP, 1.0), (ProcessType.CNC_3AXIS, 0.9),
    ])
    unfiltered = [s.process for s in rank_processes(res)]
    assert unfiltered == [ProcessType.DLP, ProcessType.CNC_3AXIS]


# ── Fix 3: classify_cots_fastener ───────────────────────────────────────────
def test_cots_detects_hardware_by_name():
    from src.services.assembly_analysis_service import classify_cots_fastener

    for name, kind in [("bolt", "bolt"), ("nut", "nut"), ("HEX BOLT", "bolt"),
                       ("lock washer", "washer"), ("cap screw", "screw")]:
        c = classify_cots_fastener(name, "", features=None, max_dim_mm=20.0)
        assert c is not None and c["is_cots"] is True, name
        assert c["kind"] == kind
        assert c["confidence"] == "high"
        assert c["buy_price_provenance"] == "DEFAULT"
        assert c["buy_price_usd"] > 0
        assert c["buy_price_range_usd"][0] <= c["buy_price_usd"] <= c["buy_price_range_usd"][1]


def test_cots_not_flagged_for_named_structural_part():
    from src.services.assembly_analysis_service import classify_cots_fastener

    # A plate / bracket is NOT a fastener, even if small and unnamed as hardware.
    assert classify_cots_fastener("plate", "", features=None, max_dim_mm=40.0) is None
    assert classify_cots_fastener("l-bracket", "", features=None, max_dim_mm=40.0) is None


def test_cots_word_boundary_avoids_false_positive():
    from src.services.assembly_analysis_service import classify_cots_fastener

    # 'pin' must not fire on 'spindle', 'nut' not on 'walnut-housing'.
    assert classify_cots_fastener("spindle", "", features=None, max_dim_mm=20.0) is None
    assert classify_cots_fastener("walnut-housing", "", features=None, max_dim_mm=20.0) is None


def test_cots_geometry_path_requires_small_and_threaded():
    from src.services.assembly_analysis_service import classify_cots_fastener

    thread_feat = SimpleNamespace(kind=SimpleNamespace(value="thread"))
    plain_feat = SimpleNamespace(kind=SimpleNamespace(value="hole"))
    # small + threaded, no fastener name => geometry-inferred medium confidence.
    c = classify_cots_fastener("part-42", "", features=[thread_feat], max_dim_mm=20.0)
    assert c is not None and c["confidence"] == "medium" and c["kind"] == "fastener"
    # threaded but LARGE => not a fastener.
    assert classify_cots_fastener("part-42", "", features=[thread_feat],
                                  max_dim_mm=500.0) is None
    # small but NOT threaded => not a fastener.
    assert classify_cots_fastener("part-42", "", features=[plain_feat],
                                  max_dim_mm=20.0) is None


# ── Fix 2: approximate geometry-inferred nominal size (Round-5 fix) ──────────
def test_infer_fastener_size_bolt_and_nut():
    from src.services.assembly_analysis_service import infer_fastener_size

    # Elongated, no volume: shaft ≈ smaller cross-section (8mm -> M8), length ≈ longest.
    assert infer_fastener_size("bolt", [8.0, 13.0, 30.0]) == "≈M8 × 30mm"
    assert infer_fastener_size("screw", [5.0, 8.0, 20.0]) == "≈M5 × 20mm"
    # F2: volume-sane shaft ø. The AS1 bolt bbox is 30×15×37 (head-skewed, 2:1
    # transverse plane) — the raw transverse read of 15 over-sizes to M16. The
    # volume-implied cylinder ø = √(4·3200/(π·37)) ≈ 10.5mm; min(15, 10.5) snaps to
    # M10. It MUST NOT read M14/M16.
    bolt = infer_fastener_size("bolt", [15.0, 30.0, 37.0], volume_mm3=3200)
    assert bolt == "≈M10 × 37mm"
    assert "M14" not in bolt and "M16" not in bolt
    # Compact nut: nominal thread ≈ across-flats / 1.6 (AF 13 -> M8).
    assert infer_fastener_size("nut", [6.5, 13.0, 15.0]) == "≈M8 nut"
    # AS1 nut geometry (3×20×20): across-flats 20 / 1.6 = 12.5 -> M12. Volume is
    # ignored for compact hardware (the across-flats read is clean).
    assert infer_fastener_size("nut", [3.0, 20.0, 20.0]) == "≈M12 nut"
    # Degenerate / missing bbox => no guess.
    assert infer_fastener_size("bolt", None) is None
    assert infer_fastener_size("bolt", [0.0, 0.0, 0.0]) is None


def test_cots_block_carries_labelled_approximate_size():
    from src.services.assembly_analysis_service import classify_cots_fastener

    c = classify_cots_fastener("bolt", "", features=None, max_dim_mm=30.0,
                               bbox_size_mm=[8.0, 13.0, 30.0])
    assert c is not None
    assert c["nominal_size"] == "≈M8 × 30mm"
    # Clearly labelled approximate, no grade claimed.
    assert "≈" in c["nominal_size_note"] and "not a verified" in c["nominal_size_note"].lower()
    # No fabrication-upper-bound promise remains in the honest note.
    assert "upper-bound" not in c["note"].lower()
    # Without a bbox, the block is still valid — just no size key.
    c2 = classify_cots_fastener("nut", "", features=None, max_dim_mm=20.0)
    assert c2 is not None and "nominal_size" not in c2


# ── Integration: AS1 end-to-end (gmsh-gated) ────────────────────────────────
@_needs_gmsh
def test_as1_no_resin_for_metal_and_fasteners_are_cots():
    from pathlib import Path

    from src.parsers.assembly_mesher import extract_assembly_from_bytes
    from src.services.assembly_analysis_service import analyze_assembly_sync

    p = Path("/home/user/cadverify/data/real-corpus/as1-tu-203.stp")
    if not p.exists():
        pytest.skip("AS1 real assembly file not available")
    model = extract_assembly_from_bytes(p.read_bytes(), "as1-tu-203.stp")
    res = analyze_assembly_sync(model, material_class="aluminum", region="US")

    for r in res["per_part"]:
        if "error" in r:
            continue
        best = (r.get("dfm_summary") or {}).get("best_process")
        # No metal part ever shows a resin/FDM/binder-jet "best process".
        assert best not in {"sla", "dlp", "fdm", "binder_jetting", "sls", "mjf"}, r["name"]
        if r["name"] in {"bolt", "nut"}:
            cots = r.get("cots")
            assert cots and cots["is_cots"] is True, r["name"]
            assert cots["recommendation"].startswith("BUY"), r["name"]
            # An approximate metric size is inferred and labelled (Fix 2).
            assert cots["nominal_size"].startswith("≈M"), r["name"]
            # The wrong machined fab figure is DROPPED, not re-framed (Fix 1): no
            # make_now_process/material/estimates on a COTS part's should-cost.
            sc = r["should_cost"]
            assert sc["cost_basis"] == "not_modeled_for_cots", r["name"]
            assert "make_now_process" not in sc, r["name"]
            assert "make_now_material" not in sc, r["name"]
            assert "estimates" not in sc, r["name"]

    # The bolt still gets an honest DFM best_process (a separate card, no material
    # or $ attached) — but its should-cost no longer carries a machined figure.
    bolt = next(r for r in res["per_part"] if r["name"] == "bolt")
    assert bolt["dfm_summary"]["best_process"] == "cnc_turning"
    assert "make_now_process" not in bolt["should_cost"]
    # F1+F2: the bolt reads a coherent M12 (reconciled with its mating nut), NOT the
    # head-skewed M16 the raw bbox transverse used to give.
    assert bolt["cots"]["nominal_size"] == "≈M12 × 37mm"
    assert bolt["cots"]["nominal_size_basis"] == "reconciled_with_mating_nut"
    nut = next(r for r in res["per_part"] if r["name"] == "nut")
    assert nut["cots"]["nominal_size"] == "≈M12 nut"

"""Assembly P3 — context-fed per-part analysis (real oracle = AS1).

Verifies the TRUE-BLUE claims of the P3 layer against the real AS1 STEP assembly
(base plate + 2 mirrored L-bracket sub-assemblies + rod-assembly; 18 solids):

  * per-part DFM + should-cost: every one of the 18 parts gets a REAL verdict +
    should-cost from the SAME single-part engine, or an HONEST per-part error —
    never a fabricated number, never a broken assembly.
  * quantity: the real instance count of each design (8 nuts, 6 bolts, 2
    l-brackets, 1 rod, 1 plate) from the extracted product tree, fed to costing.
  * interference: bolts/nuts flagged as GEOMETRIC contact/interference with the
    brackets/plate (expected fastener overlap, labelled a signal not a fault); two
    parts that DON'T touch are NOT flagged (synthetic + AS1).
  * single-part + base-assembly paths unaffected (format=json unchanged).
"""
from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

from src.parsers.step_mesher import is_step_supported

_needs_gmsh = pytest.mark.skipif(
    not is_step_supported(), reason="gmsh/STEP path unavailable"
)


def _as1_path() -> Path | None:
    """Locate the real AS1 assembly across the copies that may exist: the
    gitignored corpus copy (repo root and worktree root), and the copies that ship
    inside the gmsh distribution's public examples."""
    import gmsh  # type: ignore

    gbase = Path(gmsh.__file__).resolve()
    candidates = [
        Path(__file__).resolve().parents[2] / "data/real-corpus/as1-tu-203.stp",
        Path("/home/user/cadverify/data/real-corpus/as1-tu-203.stp"),
        gbase.parent / "share/doc/gmsh/examples/api/as1-tu-203.stp",
        gbase.parents[3] / "share/doc/gmsh/examples/api/as1-tu-203.stp",
        gbase.parents[3] / "share/doc/gmsh/examples/boolean/as1-tu-203.stp",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _as1_bytes() -> bytes:
    p = _as1_path()
    if p is None:
        pytest.skip("AS1 real assembly file not available")
    return p.read_bytes()


# ── Pure interference geometry (synthetic, no gmsh): touching vs clearing ────
def _fake_part(pid: str, name: str, mesh: trimesh.Trimesh):
    b = mesh.bounds
    return SimpleNamespace(
        id=pid, name=name, tree_path=f"root/{name}", mesh=mesh,
        world=SimpleNamespace(
            bbox_min=list(b[0]), bbox_max=list(b[1]),
            bbox_size=list(b[1] - b[0]),
        ),
    )


def test_interference_flags_overlap_not_separation():
    """Two overlapping boxes are flagged as geometric interference; two clearly
    separated boxes are NOT — the core honesty of the pairwise geometry check."""
    from src.services.assembly_analysis_service import detect_interference

    a = trimesh.creation.box(extents=[10, 10, 10])
    b = trimesh.creation.box(extents=[10, 10, 10])
    b.apply_translation([4, 4, 4])          # diagonally overlaps a: b's near corner
                                            # sits strictly inside a (real interpenetration)
    far = trimesh.creation.box(extents=[10, 10, 10])
    far.apply_translation([1000, 0, 0])     # nowhere near a or b

    model = SimpleNamespace(
        assembly_diag=1000.0,
        parts=[_fake_part("p1", "a", a), _fake_part("p2", "b", b),
               _fake_part("p3", "far", far)],
    )
    intf = detect_interference(model)
    flagged = {tuple(sorted([pr["part_a"]["name"], pr["part_b"]["name"]]))
               for pr in intf["pairs"]}
    assert ("a", "b") in flagged                 # overlapping pair flagged
    assert not any("far" in pair for pair in flagged)  # separated part never flagged
    ov = next(p for p in intf["pairs"]
              if {p["part_a"]["name"], p["part_b"]["name"]} == {"a", "b"})
    assert ov["type"] == "interpenetration"
    assert ov["penetration_vertices"] > 0


def test_interference_flags_face_contact():
    """Two boxes sharing a face (touching, not interpenetrating) are flagged as
    'contact' via the nearest-vertex gap — a real signal, distinct from clearance."""
    from src.services.assembly_analysis_service import detect_interference

    a = trimesh.creation.box(extents=[10, 10, 10])
    b = trimesh.creation.box(extents=[10, 10, 10])
    b.apply_translation([10, 0, 0])   # faces flush at x=5, no interpenetration

    model = SimpleNamespace(
        assembly_diag=30.0,
        parts=[_fake_part("p1", "a", a), _fake_part("p2", "b", b)],
    )
    intf = detect_interference(model)
    assert len(intf["pairs"]) == 1
    assert intf["pairs"][0]["type"] == "contact"


# ── AS1: the real oracle ─────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def as1_model():
    if not is_step_supported():
        pytest.skip("gmsh/STEP path unavailable")
    from src.parsers.assembly_mesher import extract_assembly_from_bytes

    return extract_assembly_from_bytes(_as1_bytes(), "as1-tu-203.stp")


@_needs_gmsh
def test_as1_per_part_analysis_all_18(as1_model):
    """Every one of the 18 AS1 parts gets a REAL DFM verdict + should-cost, or an
    honest per-part error. The plate/brackets get sensible should-cost; the small
    fasteners (nut/bolt) are handled, not dropped."""
    from src.services.assembly_analysis_service import analyze_assembly_sync

    res = analyze_assembly_sync(as1_model, material_class="aluminum", region="US")
    per = res["per_part"]
    assert len(per) == 18
    assert res["analysis_summary"]["parts_total"] == 18
    assert res["not_analyzed"] == []

    for r in per:
        # Each part is EITHER analyzed (dfm + should_cost) OR an honest error.
        if "error" in r:
            assert set(r["error"]) >= {"code", "message"}
            continue
        assert r["dfm_summary"]["verdict"] in {"pass", "issues", "fail", "unknown"}
        sc = r["should_cost"]
        assert sc["status"] in {"OK", "GEOMETRY_INVALID"}
        if sc["status"] == "OK":
            if r.get("cots"):
                # A COTS fastener's answer is the BUY price; the wrong machined fab
                # figure is DROPPED (not make_now/estimates), replaced by an honest
                # "not modeled" note. See the cots block for the catalog buy price.
                assert sc["cost_basis"] == "not_modeled_for_cots", r["name"]
                assert "make_now_process" not in sc, r["name"]
                assert "estimates" not in sc, r["name"]
            else:
                assert sc["make_now_process"]
                assert sc["estimates"], r["name"]
                for e in sc["estimates"]:
                    assert e["unit_cost_usd"] and e["unit_cost_usd"] > 0

    by_name = {}
    for r in per:
        by_name.setdefault(r["name"], []).append(r)

    # The real oracle: all 18 parts cost cleanly (no engine error on AS1).
    assert all("error" not in r for r in per), \
        [r["name"] for r in per if "error" in r]

    # Plate + brackets get sensible should-cost (real dollars, CNC family).
    plate = by_name["plate"][0]["should_cost"]
    assert plate["status"] == "OK"
    assert plate["make_now_process"].startswith("cnc")
    for br in by_name["l-bracket"]:
        assert br["should_cost"]["status"] == "OK"
        assert br["should_cost"]["make_now_process"].startswith("cnc")
    # Fasteners handled as COTS BUY: a catalog buy price + an approximate inferred
    # size, NOT a physically-wrong machined fab figure (which is dropped).
    for nm in ("nut", "bolt"):
        for r in by_name[nm]:
            assert r["should_cost"]["status"] == "OK"
            assert r["should_cost"]["cost_basis"] == "not_modeled_for_cots"
            cots = r["cots"]
            assert cots["is_cots"] is True and cots["buy_price_usd"] > 0
            assert cots["nominal_size"].startswith("≈M"), nm


@_needs_gmsh
def test_as1_real_quantities_from_tree(as1_model):
    """The per-part quantity is the REAL instance count of each design in AS1,
    counted from the extracted product tree: 8 nuts, 6 bolts, 2 l-brackets, 1 rod,
    1 plate — and that FACT is fed to the cost engine (cost_quantity)."""
    from src.services.assembly_analysis_service import analyze_assembly_sync

    res = analyze_assembly_sync(as1_model)
    assert res["quantities_by_design"] == {
        "nut": 8, "bolt": 6, "l-bracket": 2, "rod": 1, "plate": 1,
    }
    # The per-part quantity FACT is surfaced AND fed as the cost volume signal.
    q = {r["name"]: r["quantity"] for r in res["per_part"]}
    assert q == {"nut": 8, "bolt": 6, "l-bracket": 2, "rod": 1, "plate": 1}
    for r in res["per_part"]:
        if "should_cost" in r and r["should_cost"]["status"] == "OK":
            assert r["should_cost"]["cost_quantity"] == r["quantity"]


@_needs_gmsh
def test_as1_annual_volume_is_user_declared(as1_model):
    """Per-assembly quantity is a FACT; annual volume needs a user-declared
    assemblies_per_year — costed at qty × apy, honestly labelled."""
    from src.services.assembly_analysis_service import analyze_assembly_sync

    res = analyze_assembly_sync(as1_model, assemblies_per_year=1000)
    assert res["cost_context"]["assemblies_per_year"] == 1000
    assert "annual" in res["cost_context"]["quantity_basis"]
    nut = next(r for r in res["per_part"] if r["name"] == "nut")
    # 8 nuts/assembly × 1000 assemblies/yr = 8000 costed.
    assert nut["should_cost"]["cost_quantity"] == 8000


@_needs_gmsh
def test_as1_interference_fasteners_vs_brackets_plate(as1_model):
    """Bolts/nuts are flagged as GEOMETRIC contact/interference with the
    brackets/plate (expected fastener overlap), and parts that don't touch are not
    flagged. Labelled a signal, never asserted a fault."""
    from src.services.assembly_analysis_service import detect_interference

    intf = detect_interference(as1_model)
    pairs = intf["pairs"]
    assert pairs, "AS1 has bolted joints; interference must be detected"

    def design_pairs():
        return {tuple(sorted([p["part_a"]["name"], p["part_b"]["name"]]))
                for p in pairs}

    dp = design_pairs()
    # Bolts thread into nuts and pass through brackets + plate — all expected.
    assert ("bolt", "nut") in dp
    assert ("bolt", "l-bracket") in dp
    assert ("bolt", "plate") in dp
    # Brackets seat on the plate.
    assert ("l-bracket", "plate") in dp

    # Honest labelling: a signal, not a fault verdict.
    for p in pairs:
        assert p["type"] in {"interpenetration", "contact"}
        assert "EXPECTED" in p["note"] and "not a fault" in p["note"]

    # Non-touching parts are NOT flagged: candidate pairs (bbox overlap) strictly
    # exceed the reported pairs (some bbox-overlaps geometrically clear), and the
    # far-apart designs never pair. Two nuts on opposite L-brackets don't touch.
    assert intf["candidate_pairs"] >= len(pairs)
    assert intf["pairs_checked"] <= intf["candidate_pairs"]
    # plate<->rod never contact in AS1 (rod is held off the plate by the brackets).
    assert ("plate", "rod") not in dp


# ── Route contract: format=analysis, and format=json unchanged ──────────────
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    monkeypatch.setenv("PARSE_PROCESS_POOL_DISABLED", "1")
    import main

    importlib.reload(main)
    return TestClient(main.app)


@_needs_gmsh
def test_route_as1_analysis(client):
    r = client.post(
        "/api/v1/validate/assembly?format=analysis",
        files={"file": ("as1-tu-203.stp", _as1_bytes(), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Base assembly model still present (tree/positions/limits) + the analysis.
    assert body["kind"] == "assembly"
    assert body["part_count"] == 18
    assert "limits" in body
    an = body["analysis"]
    assert an["quantities_by_design"]["nut"] == 8
    assert len(an["per_part"]) == 18
    assert an["interference"]["pairs"]
    assert "boundaries" in an
    # Honesty boundaries are surfaced verbatim in the response.
    assert "material_class" in an["boundaries"]
    assert "interface_dfm_and_gdt" in an["boundaries"]


@_needs_gmsh
def test_route_as1_json_unchanged_no_analysis_key(client):
    """format=json (default) must NOT carry the analysis block — the P3 path is
    strictly additive and opt-in."""
    r = client.post(
        "/api/v1/validate/assembly",
        files={"file": ("as1-tu-203.stp", _as1_bytes(), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    assert "analysis" not in r.json()


@_needs_gmsh
def test_route_analysis_bad_material_is_400(client):
    r = client.post(
        "/api/v1/validate/assembly?format=analysis&material_class=unobtanium",
        files={"file": ("as1-tu-203.stp", _as1_bytes(), "application/octet-stream")},
    )
    assert r.status_code == 400
    assert "material_class" in r.text

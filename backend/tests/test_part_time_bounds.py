"""Parts that failed even alone on an idle box (capacity report C1), each within a CPU-time bound.

The bounds are CPU seconds of this process (``time.process_time``: every thread),
not wall time, so they hold on an idle or a loaded machine.

* nist_periodic_ctc05: the app asks the assembly probe first. The probe meshed the
  file, and its first meshing strategy grinds 220 s on the periodic surface before
  failing, so every check of it ended in a 504. A file of one solid is now read
  without meshing it (``/validate`` meshes it, with its own capped retry ladder).
* A 9 KB bushing (20 mm across, 1 mm wall, 30 mm long) meshes to 202,754 faces.
  Its analysis took 154 s and its price 271 s: the wire-EDM reach check tested
  every facet against every vertex, the inscribed-diameter reading rebuilt a
  vertex tree for every 8 points, and the resin pad's outline unioned 96,884
  runs of faces two at a time.
* A 30-body assembly took 45-62 s against the 60 s limit: four threads contending
  for the GIL were slower than one.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.parsers.step_mesher import is_step_supported

ASSETS = Path(__file__).parent / "assets"
_needs_gmsh = pytest.mark.skipif(not is_step_supported(), reason="gmsh/STEP path unavailable")


@_needs_gmsh
def test_the_probe_reads_a_single_periodic_part_without_meshing_it():
    from src.parsers.assembly_mesher import extract_assembly_from_bytes

    data = (ASSETS / "nist_periodic_ctc05.stp").read_bytes()
    start = time.process_time()
    model = extract_assembly_from_bytes(data, "nist_periodic_ctc05.stp", mesh_single_part=False)
    used = time.process_time() - start
    assert (model.kind, model.part_count) == ("single_part", 1)
    part = model.parts[0]
    assert part.mesh is None and part.mesh_ref is None
    assert part.geometry_summary.num_triangles == 0 and model.skipped == []
    assert part.world.volume > 0 and all(d > 0 for d in part.world.bbox_size)
    # Meshing it used 220 s of CPU; reading it, about 0.3 s.
    assert used < 5.0, used


@_needs_gmsh
def test_a_single_part_is_still_meshed_for_the_assembly_view_and_analysis():
    from src.parsers.assembly_mesher import extract_assembly_from_bytes

    model = extract_assembly_from_bytes((ASSETS / "plate-with-boss.step").read_bytes(), "plate.step")
    assert model.kind == "single_part"
    assert model.parts[0].mesh is not None and model.parts[0].geometry_summary.num_triangles > 0


@pytest.fixture
def client(monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("PARSE_PROCESS_POOL_DISABLED", "1")
    import main

    importlib.reload(main)
    return TestClient(main.app)


@pytest.mark.parametrize("fmt,meshed", [("json", False), ("glb", True), ("analysis", True)])
def test_only_the_probe_reads_a_single_part_unmeshed(client, monkeypatch, fmt, meshed):
    from src.api import routes

    asked = []

    async def _extract(data, filename, *, mesh_single_part=True):
        asked.append(mesh_single_part)
        raise routes.HTTPException(status_code=400, detail="stop here")

    monkeypatch.setattr(routes, "_extract_assembly_async", _extract)
    r = client.post(f"/api/v1/validate/assembly?format={fmt}",
                    files={"file": ("part.step", b"ISO-10303-21;", "application/octet-stream")})
    assert r.status_code == 400, r.text
    assert asked == [meshed]


@_needs_gmsh
def test_the_probe_answers_for_the_periodic_part(client):
    start = time.process_time()
    r = client.post("/api/v1/validate/assembly?format=json",
                    files={"file": ("nist_periodic_ctc05.stp", (ASSETS / "nist_periodic_ctc05.stp").read_bytes(),
                                    "application/octet-stream")})
    used = time.process_time() - start
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["kind"], body["part_count"]) == ("single_part", 1)
    assert used < 10.0, used


def _tube_with_tipped_walls():
    """A 20 x 18 x 30 mm tube whose wall triangles tip a hair up and down in turn, as a CAD
    mesher's do: its vertices sit on the circles between the coarser rings' (673 runs a side)."""
    import numpy as np
    import trimesh

    mesh = trimesh.creation.annulus(r_min=9.0, r_max=10.0, height=30.0, sections=48)
    for _ in range(3):
        mesh = mesh.subdivide()
    vertices = mesh.vertices.copy()
    radius = np.hypot(vertices[:, 0], vertices[:, 1])
    for target in (9.0, 10.0):
        near = np.abs(radius - target) < 0.2
        vertices[near, :2] *= (target / radius[near])[:, None]
    return trimesh.Trimesh(vertices, mesh.faces, process=False)


@pytest.mark.parametrize("up", [1.0, -1.0])
def test_the_resin_pad_outline_traced_at_once_is_trimeshs(monkeypatch, up):
    from trimesh.path.polygons import projected

    from src.costing import print_model

    mesh = _tube_with_tipped_walls()
    exact = projected(mesh, normal=[0.0, 0.0, up])
    # Up to the threshold, trimesh's own outline, to the bit.
    monkeypatch.setattr(print_model, "_OUTLINE_RUNS_AT_ONCE", 100_000)
    assert print_model._projected(mesh, up).equals_exact(exact, 0.0)
    # Past it, each run's loop traced at once and the loops unioned at once: the same outline.
    monkeypatch.setattr(print_model, "_OUTLINE_RUNS_AT_ONCE", 0)
    fast = print_model._projected(mesh, up)
    assert fast.area == pytest.approx(exact.area, rel=1e-12)
    assert fast.symmetric_difference(exact).area < 1e-10 * exact.area
    assert fast.length == pytest.approx(exact.length, rel=1e-9)


@_needs_gmsh
def test_a_thin_walled_bushing_is_checked_and_priced_within_its_cpu_budget():
    from src.api import routes
    from src.costing import EstimateOptions, estimate_decision, report_to_dict

    mesh, _ = routes._parse_mesh((ASSETS / "bushing-1mm-wall.step").read_bytes(), "bushing-1mm-wall.step")
    assert len(mesh.faces) > 150_000  # the fine mesh that made it slow
    start = time.process_time()
    result, analysed, ctx = routes._run_cost_engine_ctx(mesh.copy(), "bushing-1mm-wall.step")
    checked = time.process_time() - start
    options = EstimateOptions(quantities=[1, 100, 10000], material_class="polymer",
                              material_class_is_user=False, region="US", region_is_user=False)
    start = time.process_time()
    report = report_to_dict(estimate_decision(result, analysed, ctx.features, options))
    priced = time.process_time() - start
    codes = {i.code for s in result.process_scores for i in s.issues}
    # A through bore: a wire reaches every face.
    assert "WIRE_CANNOT_REACH" not in codes
    assert ctx.maximum_inscribed_diameter == pytest.approx(1.0, abs=0.01)  # the 1 mm wall
    assert report["estimates"]
    # Every analyzer: 140 s of CPU before (wire reach 107 s, inscribed diameter 21 s), about 10 s now.
    assert checked < 45.0, checked
    # The price: 136-175 s before (the resin pad's outline), about 15 s now.
    assert priced < 60.0, priced


@_needs_gmsh
def test_a_thirty_body_assembly_is_analysed_on_one_thread(tmp_path):
    import gmsh

    from src.parsers.assembly_mesher import extract_assembly_from_bytes
    from src.services import assembly_analysis_service as svc

    assert svc._analyze_workers() == 1
    # Ten copies of a bracket (plate, boss, bore, four holes), as the capacity test's asm-30 is thirty.
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        body, _ = occ.fuse([(3, occ.addBox(0, 0, 0, 60, 40, 6))], [(3, occ.addCylinder(30, 20, 6, 0, 0, 14, 9))])
        holes = [occ.addCylinder(x, y, -1, 0, 0, 30, 2.6) for x, y in ((8, 8), (52, 8), (8, 32), (52, 32))]
        occ.cut(body, [(3, h) for h in holes] + [(3, occ.addCylinder(30, 20, -1, 0, 0, 30, 4.5))])
        occ.synchronize()
        base = gmsh.model.getEntities(3)
        for i in range(1, 10):
            occ.translate(occ.copy(base), (i % 3) * 70.0, (i // 3) * 50.0, 0)
        occ.synchronize()
        path = tmp_path / "asm10.step"
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    model = extract_assembly_from_bytes(path.read_bytes(), "asm10.step")
    assert model.part_count == 10
    start = time.process_time()
    out = svc.analyze_assembly_sync(model, time_budget_sec=600)
    used = time.process_time() - start
    assert out["analysis_summary"]["parts_ok"] == 10 and not out["not_analyzed"]
    # About 0.6 s of CPU a body on one thread; four threads used about twice that.
    assert used < 30.0, used

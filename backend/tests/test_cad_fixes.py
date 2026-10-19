"""Fixes ScaleCAD makes itself on a copy of a stored part (round 6).

Each fix runs on real repo parts and is re-checked with the real engine; the
endpoint is org-scoped like the stored-source routes, needs the pilot
entitlement like mesh repair, never counts a check, and never changes the
original bytes.
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.fixes import brep_fixes as bf
from src.services import cad_fix_service as svc

ASSETS = Path(__file__).parent / "assets"
TRAP = Path(__file__).parent / "trap-corpus"
ORG_A = "01JORGAAAAAAAAAAAAAAAAAAAA"
ORG_B = "01JORGBBBBBBBBBBBBBBBBBBBB"
# user id -> (org, org role)
USERS = {1: (ORG_A, "member"), 2: (ORG_B, "admin"), 3: (ORG_A, "viewer")}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _findings(data: bytes, filename: str) -> set[tuple[str, str]]:
    """Re-check bytes with the real engine; return {(code, process)}."""
    from src.api.routes import _parse_mesh, _run_cost_engine_ctx

    mesh, _ = _parse_mesh(data, filename)
    result, _m, _ctx = _run_cost_engine_ctx(mesh, filename)
    out = {(i.code, "*") for i in result.universal_issues}
    for score in result.process_scores:
        out |= {(i.code, score.process.value) for i in score.issues}
    return out


def _codes(findings: set[tuple[str, str]]) -> set[str]:
    return {code for code, _p in findings}


def _sealed_box_step(tmp_path: Path) -> bytes:
    """A 30 x 24 x 16 mm block with a sealed 22 x 16 x 8 mm cavity, made with OCC."""
    import gmsh

    path = tmp_path / "sealed-box.step"
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("sealed")
        outer = gmsh.model.occ.addBox(0, 0, 0, 30, 24, 16)
        inner = gmsh.model.occ.addBox(4, 4, 4, 22, 16, 8)
        gmsh.model.occ.cut([(3, outer)], [(3, inner)])
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path.read_bytes()


def _unsewn_box_step(tmp_path: Path) -> bytes:
    """A box exported as six loose faces with micrometre gaps: no solid in the file."""
    import gmsh

    path = tmp_path / "unsewn.step"
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("unsewn")
        box = gmsh.model.occ.addBox(0, 0, 0, 30, 20, 10)
        gmsh.model.occ.synchronize()
        faces = [t for _d, t in gmsh.model.getBoundary([(3, box)], oriented=False)]
        copies = gmsh.model.occ.copy([(2, f) for f in faces])
        gmsh.model.occ.remove([(3, box)], recursive=True)
        for i, dt in enumerate(copies):
            gmsh.model.occ.translate([dt], 2e-5 * (i % 3), 1e-5 * (i % 2), 0)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path.read_bytes()


# ---------------------------------------------------------------------------
# The fixes themselves, re-checked with the real engine
# ---------------------------------------------------------------------------


def test_drain_holes_open_a_sealed_stl_cavity_and_the_recheck_clears_it():
    raw = (TRAP / "trap-wall-0.5mm-shell.stl").read_bytes()
    before = _findings(raw, "shell.stl")
    assert "TRAPPED_VOLUME" in _codes(before) and ("MULTIPLE_BODIES", "*") in before

    out = bf.run_fix("drain_holes", raw, ".stl", {"diameter_mm": 5.0})
    assert out.applied, out.reason
    assert out.suffix == ".stl"
    roles = [h["role"] for h in out.details["holes"]]
    assert roles == ["drain", "vent"]
    drain = out.details["holes"][0]
    assert drain["direction"] == [0, 0, -1], "the drain leaves through the floor"
    assert drain["wall_mm"] == pytest.approx(0.5, abs=0.01)
    after = _findings(out.data, "shell-drained.stl")
    assert "TRAPPED_VOLUME" not in _codes(after)
    assert ("MULTIPLE_BODIES", "*") not in after
    # Two 5 mm holes through 0.5 mm walls: 2 * pi * 2.5^2 * 0.5 = 19.6 mm3.
    removed = out.details["mesh_volume_before_mm3"] - out.details["mesh_volume_after_mm3"]
    assert removed == pytest.approx(19.6, rel=0.05)
    assert raw == (TRAP / "trap-wall-0.5mm-shell.stl").read_bytes()


def test_drain_holes_on_a_brep_cavity_write_a_step_that_reimports_clean(tmp_path):
    raw = _sealed_box_step(tmp_path)
    assert "TRAPPED_VOLUME" in _codes(_findings(raw, "sealed.step"))
    out = bf.run_fix("drain_holes", raw, ".step", {"diameter_mm": 5.0})
    assert out.applied, out.reason
    assert out.suffix == ".step" and out.data.startswith(b"ISO-10303-21")
    assert out.details["cavities_opened"] == 1
    assert [h["wall_mm"] for h in out.details["holes"]] == [4.0, 4.0]
    expected = 2 * 3.141592653589793 * 2.5 ** 2 * 4.0
    assert out.details["brep_volume_before_mm3"] - out.details["brep_volume_after_mm3"] == pytest.approx(expected, rel=1e-3)
    after = _findings(out.data, "sealed-drained.step")
    assert not {"TRAPPED_VOLUME", "MULTIPLE_BODIES"} & _codes(after)
    # Deterministic bytes: the same fix on the same file is the same new part.
    again = bf.run_fix("drain_holes", raw, ".step", {"diameter_mm": 5.0})
    assert hashlib.sha256(again.data).digest() == hashlib.sha256(out.data).digest()


def test_drain_holes_refuse_parts_without_a_sealed_cavity():
    cube = (TRAP / "control-cube-10mm.stl").read_bytes()
    out = bf.run_fix("drain_holes", cube, ".stl", {"diameter_mm": 5.0})
    assert not out.applied and out.data is None
    assert "No sealed cavity" in out.reason
    # A cavity that already has an (undersized) drain is one shell: not ours to change.
    gap = (TRAP / "trap-hollow-drain-2mm-KNOWN-GAP.stl").read_bytes()
    assert not bf.run_fix("drain_holes", gap, ".stl", {"diameter_mm": 5.0}).applied


def test_fillet_rounds_the_inside_corners_and_the_recheck_clears_them():
    raw = (ASSETS / "plate-with-boss.step").read_bytes()
    before = _findings(raw, "plate-with-boss.step")
    assert {"SHARP_INTERNAL_CORNERS", "MISSING_FILLETS"} <= _codes(before)
    out = bf.run_fix("fillet_inside_corners", raw, ".step", {"radius_mm": 1.0})
    assert out.applied, out.reason
    assert out.details["edges_rounded"] == 4
    assert out.details["brep_volume_after_mm3"] > out.details["brep_volume_before_mm3"]
    after = _findings(out.data, "plate-with-boss-rounded.step")
    assert not {"SHARP_INTERNAL_CORNERS", "MISSING_FILLETS"} & _codes(after)


def test_fillet_refuses_cleanly():
    stl = (TRAP / "trap-wall-0.5mm-shell.stl").read_bytes()
    out = bf.run_fix("fillet_inside_corners", stl, ".stl", {"radius_mm": 0.5})
    assert not out.applied and "STL" in out.reason
    # The bored block has no inside corners (its bore edges are convex).
    bored = (ASSETS / "bored-block-mm.iges").read_bytes()
    out = bf.run_fix("fillet_inside_corners", bored, ".iges", {"radius_mm": 0.5})
    assert not out.applied and "No sharp inside corners" in out.reason
    # A radius larger than the walls allow is OpenCASCADE's refusal, reported.
    boss = (ASSETS / "plate-with-boss.step").read_bytes()
    out = bf.run_fix("fillet_inside_corners", boss, ".step", {"radius_mm": 20.0})
    assert not out.applied and out.data is None


def test_heal_sews_loose_faces_into_a_solid_and_refuses_a_missing_face(tmp_path):
    raw = _unsewn_box_step(tmp_path)
    assert ("NON_WATERTIGHT", "*") in _findings(raw, "unsewn.step")
    out = bf.run_fix("heal_brep", raw, ".step", {})
    assert out.applied, out.reason
    assert out.details["solids_before"] == 0 and out.details["solids_after"] == 1
    assert out.details["brep_volume_after_mm3"] == pytest.approx(6000.0, rel=1e-4)
    assert ("NON_WATERTIGHT", "*") not in _findings(out.data, "unsewn-healed.step")
    # Flags: the open shell and the loose faces it reads as are both the heal fix.
    path = tmp_path / "unsewn.step"
    path.write_bytes(raw)
    by = {g["code"]: g for g in svc.fix_options(_analysis_dict(path), ".step")["findings"]}
    assert by["NON_WATERTIGHT"]["fix"] == "heal_brep" and by["NON_WATERTIGHT"]["can_fix"]
    assert by["MULTIPLE_BODIES"]["fix"] == "heal_brep" and by["MULTIPLE_BODIES"]["can_fix"]
    # open-bored-block is missing its top face: sewing can't invent one.
    open_block = (ASSETS / "open-bored-block-mm.iges").read_bytes()
    refused = bf.run_fix("heal_brep", open_block, ".iges", {})
    assert not refused.applied and "missing" in refused.reason


def test_draft_needs_ocp_and_is_offered_only_when_it_imports(monkeypatch):
    from src.fixes import draft_ocp

    monkeypatch.setattr(draft_ocp, "available", lambda: False)
    monkeypatch.setenv("CAD_FIX_DRAFT_ENABLED", "1")
    ok, why = svc.FIXES["add_draft"].available()
    assert not ok and "cadquery-ocp" in why
    # Installing OCP alone doesn't turn it on: it also needs the explicit flag.
    monkeypatch.setattr(draft_ocp, "available", lambda: True)
    monkeypatch.delenv("CAD_FIX_DRAFT_ENABLED")
    ok, why = svc.FIXES["add_draft"].available()
    assert not ok and "CAD_FIX_DRAFT_ENABLED" in why
    monkeypatch.setenv("CAD_FIX_DRAFT_ENABLED", "1")
    assert svc.FIXES["add_draft"].available() == (True, None)


def test_draft_tilts_side_walls_when_ocp_is_installed():
    pytest.importorskip("OCP")
    raw = (ASSETS / "box-mm.iges").read_bytes()
    out = bf.run_fix("add_draft", raw, ".iges", {"angle_deg": 1.5})
    assert out.applied, out.reason
    assert out.details["faces_drafted"] == 4
    after = _findings(out.data, "box-drafted.iges")
    assert ("INSUFFICIENT_DRAFT", "injection_molding") not in after


# ---------------------------------------------------------------------------
# Can-fix flags
# ---------------------------------------------------------------------------


def _analysis_dict(path: Path) -> dict:
    from src.api.routes import _parse_mesh, _run_cost_engine_ctx, _to_response

    mesh, _ = _parse_mesh(path.read_bytes(), path.name)
    result, _m, ctx = _run_cost_engine_ctx(mesh, path.name)
    return _to_response(result, ctx.features)


def test_can_fix_flags_for_an_stl_with_a_sealed_cavity():
    result = _analysis_dict(TRAP / "trap-wall-0.5mm-shell.stl")
    opts = svc.fix_options(result, ".stl")
    by = {g["code"]: g for g in opts["findings"]}
    assert by["TRAPPED_VOLUME"]["can_fix"] and by["TRAPPED_VOLUME"]["fix"] == "drain_holes"
    # The rule's own numbers: 5 mm for MJF/metal powder, 3.5 resin/SLS, 3.0 filament.
    assert by["TRAPPED_VOLUME"]["required"]["mjf"] == 5.0
    assert by["TRAPPED_VOLUME"]["required"]["fdm"] == 3.0
    assert by["TRAPPED_VOLUME"]["params"] == {"diameter_mm": 5.0}
    assert by["MULTIPLE_BODIES"]["can_fix"] and by["MULTIPLE_BODIES"]["whole_part"]
    for code in ("SHARP_INTERNAL_CORNERS", "MISSING_FILLETS", "INSUFFICIENT_DRAFT", "THIN_WALL"):
        assert by[code]["can_fix"] is False and by[code]["why_not"], code
    assert opts["families"] == ["bodies", "drain"]
    assert opts["can_fix_count"] == 2


def test_can_fix_flags_for_a_step_part_and_after_a_failed_attempt(monkeypatch):
    from src.fixes import draft_ocp

    monkeypatch.setattr(draft_ocp, "available", lambda: False)
    result = _analysis_dict(ASSETS / "plate-with-boss.step")
    opts = svc.fix_options(result, ".step")
    by = {g["code"]: g for g in opts["findings"]}
    # Milling asks for 0.5 mm; ScaleCAD rounds at 1.0 mm at least (still meets it)
    # because 0.5 mm fillets tessellate creased enough to read as sharp again.
    assert by["SHARP_INTERNAL_CORNERS"]["can_fix"] and by["SHARP_INTERNAL_CORNERS"]["params"] == {"radius_mm": 1.0}
    assert by["SHARP_INTERNAL_CORNERS"]["required"]["cnc_3axis"] == 0.5
    assert by["MISSING_FILLETS"]["params"] == {"radius_mm": 3.0}, "covers sand casting and forging"
    assert by["INSUFFICIENT_DRAFT"]["can_fix"] is False and "cadquery-ocp" in by["INSUFFICIENT_DRAFT"]["why_not"]
    assert "corners" in opts["families"] and "draft" not in opts["families"]
    # The last attempt didn't clear the corners: no longer shown as fixable.
    failed = {"fillet_inside_corners": {"outcome": "not_cleared", "summary": "Re-check still shows the targeted findings.",
                                        "targeted_remaining_codes": ["SHARP_INTERNAL_CORNERS"]}}
    by = {g["code"]: g for g in svc.fix_options(result, ".step", failed)["findings"]}
    assert by["SHARP_INTERNAL_CORNERS"]["can_fix"] is False
    assert by["SHARP_INTERNAL_CORNERS"]["attempt"]["outcome"] == "not_cleared"


def test_an_undersized_existing_drain_is_not_offered():
    result = _analysis_dict(TRAP / "trap-hollow-drain-2mm-KNOWN-GAP.stl")
    trapped = [g for g in svc.fix_options(result, ".stl")["findings"] if g["code"] == "TRAPPED_VOLUME"]
    assert trapped and all(not g["can_fix"] for g in trapped)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "objects"))
    monkeypatch.setenv("ADMISSION_DISABLED", "1")
    return tmp_path


def _save(org: str, name: str, raw: bytes) -> str:
    from src.services.source_artifact_service import save_source_artifact

    digest = hashlib.sha256(raw).hexdigest()
    asyncio.run(save_source_artifact(org, digest, name, raw))
    return digest


def _fake_session():
    session = AsyncMock()
    session.add = MagicMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    async def _flush():
        return None

    session.flush = _flush
    return session


def _app(user_id: int | None, *, pilot: bool = True) -> FastAPI:
    from src.api.part_fixes import router
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.auth.validation_caps import paid_access_required, require_paid_access
    from src.db.engine import get_db_session

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/v1/parts")
    if user_id is not None:
        app.dependency_overrides[require_api_key] = lambda: AuthedUser(
            user_id=user_id, api_key_id=0, key_prefix="session", role="analyst")

    def _paid():
        if not pilot:
            raise paid_access_required()

    app.dependency_overrides[require_paid_access] = _paid

    async def _session():
        yield _fake_session()

    app.dependency_overrides[get_db_session] = _session
    return app


@pytest.fixture(autouse=True)
def _memberships(monkeypatch):
    async def lookup(user_id: int):
        return USERS.get(user_id)

    monkeypatch.setattr("src.auth.rbac.lookup_org_membership", lookup)


def test_apply_drain_fix_end_to_end(store):
    raw = (TRAP / "trap-wall-0.5mm-shell.stl").read_bytes()
    digest = _save(ORG_A, "shell.stl", raw)
    client = TestClient(_app(1))

    listing = client.get(f"/api/v1/parts/{digest}/fixes")
    assert listing.status_code == 200, listing.text
    assert listing.json()["format"] == "stl" and listing.json()["analysis"] is None

    r = client.post(f"/api/v1/parts/{digest}/fixes/drain_holes?with_cost=false")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] is True and body["outcome"] == "cleared"
    assert body["fix"]["params"] == {"diameter_mm": 5.0}, "the largest drain the rules ask for"
    assert body["verification"]["checks_used"] == 0 and body["verification"]["comparable"]
    fixed_hash = body["fixed"]["mesh_hash"]
    assert fixed_hash != digest and body["fixed"]["sha256"] == fixed_hash
    assert body["original"]["sha256"] == digest
    cleared = {(f["code"], f["process"]) for f in body["findings_cleared"]}
    assert ("MULTIPLE_BODIES", None) in cleared and ("TRAPPED_VOLUME", "mjf") in cleared
    assert {f["code"] for f in body["targeted"]["remaining"]} == set()
    assert body["volume_change_pct"] == pytest.approx(-1.72, abs=0.05)
    assert body["volume_warning"] is None
    assert body["lineage"]["parent_mesh_hash"] == digest and body["lineage"]["fix"] == "drain_holes"

    # The original is untouched; the copy is downloadable, the original is not.
    from src.services.source_artifact_service import read_source_artifact

    kept, _ = asyncio.run(read_source_artifact(ORG_A, digest))
    assert kept == raw
    dl = client.get(body["download"]["url"])
    assert dl.status_code == 200
    assert hashlib.sha256(dl.content).hexdigest() == fixed_hash
    assert dl.headers["content-type"].startswith("model/stl")
    # No saved check row in this test, so the parent's name falls back to "part".
    assert 'filename="part-drained.stl"' in dl.headers["content-disposition"]
    assert client.get(f"/api/v1/parts/{digest}/fixed-file").status_code == 404
    import base64

    assert base64.b64decode(body["fixed_file_b64"]) == dl.content

    # The fixed part knows its parent; the parent remembers the attempt.
    child = client.get(f"/api/v1/parts/{fixed_hash}/fixes").json()
    assert child["derived_from"]["parent_mesh_hash"] == digest
    attempts = asyncio.run(svc.read_attempts(ORG_A, digest))
    assert attempts["drain_holes"]["outcome"] == "cleared"
    assert attempts["drain_holes"]["fixed_mesh_hash"] == fixed_hash


def test_prices_before_and_after_at_the_requested_quantities(store):
    raw = (TRAP / "trap-wall-0.5mm-shell.stl").read_bytes()
    digest = _save(ORG_A, "shell.stl", raw)
    r = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/fixes/drain_holes?qty=10,1000")
    assert r.status_code == 200, r.text
    prices = r.json()["prices"]
    assert prices["quantities"] == [10, 1000] and prices["basis"] == "request"
    assert [p["qty"] for p in prices["before"]] == [10, 1000]
    after = {p["qty"]: p for p in prices["after"]}
    for p in prices["before"] + prices["after"]:
        assert set(p) == {"qty", "process", "material", "unit_cost_usd"}
    assert any(p["unit_cost_usd"] for p in after.values()), "something can make the drained part"


def test_auth_and_org_scoping(store):
    raw = (TRAP / "trap-wall-0.5mm-shell.stl").read_bytes()
    digest = _save(ORG_A, "shell.stl", raw)
    paths = [("get", f"/api/v1/parts/{digest}/fixes"), ("post", f"/api/v1/parts/{digest}/fixes/drain_holes"),
             ("get", f"/api/v1/parts/{digest}/fixed-file")]
    for method, path in paths:
        assert getattr(TestClient(_app(None)), method)(path).status_code == 401
        assert getattr(TestClient(_app(99)), method)(path).status_code == 403
        # Another org's hash is the same 404 as a part never stored.
        other = getattr(TestClient(_app(2)), method)(path)
        missing = getattr(TestClient(_app(1)), method)(path.replace(digest, "0" * 64))
        assert other.status_code == missing.status_code == 404
    # A viewer can read the flags but can't add a part.
    viewer = TestClient(_app(3))
    assert viewer.get(f"/api/v1/parts/{digest}/fixes").status_code == 200
    assert viewer.post(f"/api/v1/parts/{digest}/fixes/drain_holes").status_code == 403
    # A member without the pilot entitlement gets the repair tool's 403.
    r = TestClient(_app(1, pilot=False)).post(f"/api/v1/parts/{digest}/fixes/drain_holes")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "paid_access_required"
    assert TestClient(_app(1)).get("/api/v1/parts/not-a-hash/fixes").status_code == 404


def test_request_errors_and_limits(store, monkeypatch):
    raw = (TRAP / "trap-wall-0.5mm-shell.stl").read_bytes()
    digest = _save(ORG_A, "shell.stl", raw)
    client = TestClient(_app(1))
    assert client.post(f"/api/v1/parts/{digest}/fixes/thicken").status_code == 404
    assert client.post(f"/api/v1/parts/{digest}/fixes/drain_holes?value=0.1").status_code == 400
    assert client.post(f"/api/v1/parts/{digest}/fixes/drain_holes?material_class=unobtainium").status_code == 400
    r = client.post(f"/api/v1/parts/{digest}/fixes/fillet_inside_corners")
    assert r.status_code == 422 and "STL" in r.json()["detail"]
    monkeypatch.setenv("CAD_FIX_MAX_MB", "0.001")
    assert client.post(f"/api/v1/parts/{digest}/fixes/drain_holes").status_code == 413


def test_failure_paths_return_the_original_and_no_file(store, monkeypatch):
    from concurrent.futures.process import BrokenProcessPool

    raw = (TRAP / "trap-wall-0.5mm-shell.stl").read_bytes()
    digest = _save(ORG_A, "shell.stl", raw)
    client = TestClient(_app(1))
    calls = []

    async def timeout(*args, **kwargs):
        calls.append(args)
        raise asyncio.TimeoutError

    monkeypatch.setattr(svc, "run_fix_isolated", timeout)
    monkeypatch.setenv("CAD_FIX_TIMEOUT_SEC", "1")
    r = client.post(f"/api/v1/parts/{digest}/fixes/drain_holes?with_cost=false")
    body = r.json()
    assert r.status_code == 200 and body["applied"] is False
    assert body["fixed"] is None and body["download"] is None and body["fixed_file_b64"] is None
    assert body["original"]["sha256"] == digest
    assert asyncio.run(svc.read_attempts(ORG_A, digest))["drain_holes"]["applied"] is False

    async def crash(*args, **kwargs):
        calls.append(args)
        raise BrokenProcessPool("segfault")

    calls.clear()
    monkeypatch.setattr(svc, "run_fix_isolated", crash)
    monkeypatch.setenv("CAD_FIX_TIMEOUT_SEC", "60")
    body = client.post(f"/api/v1/parts/{digest}/fixes/drain_holes?with_cost=false").json()
    assert body["applied"] is False and "crashed" in body["reason"]
    assert len(calls) == 2 and calls[1][3].get("_uniform_mesh") is True, "retried once with MeshAdapt"

    async def no_cavity(fix_id, data, suffix, params, cap):
        return bf.FixOutcome(False, None, suffix, "No sealed cavity was found inside the mesh."), 12.0

    monkeypatch.setattr(svc, "run_fix_isolated", no_cavity)
    body = client.post(f"/api/v1/parts/{digest}/fixes/drain_holes?with_cost=false").json()
    assert body["applied"] is False and body["reason"].startswith("No sealed cavity")


def test_the_isolated_worker_really_runs_and_is_bounded():
    raw = (TRAP / "trap-wall-0.5mm-shell.stl").read_bytes()
    out, ms = asyncio.run(svc.run_fix_isolated("drain_holes", raw, ".stl", {"diameter_mm": 5.0}, 60))
    assert out.applied and ms > 0
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(svc.run_fix_isolated("drain_holes", raw, ".stl", {"diameter_mm": 5.0}, 0.01))


def test_fixing_never_counts_a_check_and_needs_the_pilot_entitlement():
    from src.api.part_fixes import router
    from src.auth.org_limits import enforce_org_limits
    from src.auth.validation_caps import enforce_validation_caps, require_paid_access

    def calls(dependant):
        for d in dependant.dependencies:
            yield d.call
            yield from calls(d)

    for route in router.routes:
        found = set(calls(route.dependant))
        assert enforce_validation_caps not in found, route.path
        assert enforce_org_limits not in found, route.path
        if "POST" in route.methods:
            assert require_paid_access in found


def test_a_fix_that_does_not_reimport_is_not_offered(store, monkeypatch):
    raw = (TRAP / "trap-wall-0.5mm-shell.stl").read_bytes()
    digest = _save(ORG_A, "shell.stl", raw)

    async def garbage(fix_id, data, suffix, params, cap):
        return bf.FixOutcome(True, b"solid broken\nendsolid broken\n", ".stl", None, {}), 5.0

    monkeypatch.setattr(svc, "run_fix_isolated", garbage)
    body = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/fixes/drain_holes?with_cost=false").json()
    assert body["applied"] is False and "re-check" in body["reason"]
    assert body["download"] is None


def test_no_saved_check_means_no_findings_and_parameters_are_bounded():
    assert svc.fix_options(None, ".step")["findings"] == []
    with pytest.raises(svc.FixRequestError):
        svc.resolve_params(svc.FIXES["drain_holes"], 99.0, {}, ".stl")
    assert svc.resolve_params(svc.FIXES["fillet_inside_corners"], 0.5, {}, ".step") == {"radius_mm": 0.5}

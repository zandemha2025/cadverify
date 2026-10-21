"""Mesh repair that says what was open and how it ended, and repair of a kept part.

* The repair welds faces that touch but were never joined before it closes
  gaps, so an unsewn box and the open bored block come back as the solids they
  were authored as instead of with the bore filled.
* Every repair ends in one ``outcome`` with a plain ``summary``.
* ``POST /api/v1/parts/{mesh_hash}/repair`` repairs the organization's kept
  source: no upload, no check used, org-scoped like the other stored-source
  routes, on every plan (a free account gets the repair ceiling), and the
  repaired copy is a new part linked to its parent and downloadable.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
import trimesh
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.services import repair_service as rs

ASSETS = Path(__file__).parent / "assets"
OPEN_BORED_BLOCK = ASSETS / "open-bored-block-mm.iges"
# 20 x 15 x 10 mm block with a 6 mm through-bore: 3000 - pi * 3^2 * 10 mm3.
BORED_BLOCK_MM3 = 3000.0 - np.pi * 9.0 * 10.0
ORG_A = "01JORGAAAAAAAAAAAAAAAAAAAA"
ORG_B = "01JORGBBBBBBBBBBBBBBBBBBBB"
# user id -> (org, org role)
USERS = {1: (ORG_A, "member"), 2: (ORG_B, "admin"), 3: (ORG_A, "viewer")}


# ---------------------------------------------------------------------------
# meshes
# ---------------------------------------------------------------------------


def _box_missing(n_faces: int, size: float = 10.0) -> trimesh.Trimesh:
    box = trimesh.creation.box(extents=[size] * 3)
    return trimesh.Trimesh(box.vertices, box.faces[:-n_faces], process=False)


def _unsewn_box(gap: float = 1e-5) -> trimesh.Trimesh:
    """A 30 x 20 x 10 box whose six sides each carry their own vertices, `gap` mm apart."""
    box = trimesh.creation.box(extents=[30.0, 20.0, 10.0]).subdivide()
    verts, faces = [], []
    normals = np.round(box.face_normals).astype(int)
    for side, n in enumerate({tuple(x) for x in normals}):
        mask = np.all(normals == n, axis=1)
        used = np.unique(box.faces[mask])
        remap = {v: i + len(verts) for i, v in enumerate(used)}
        verts.extend(box.vertices[used] + gap * side * np.array([1.0, 0.5, 0.25]))
        faces.extend([[remap[v] for v in f] for f in box.faces[mask]])
    return trimesh.Trimesh(np.array(verts), np.array(faces), process=False)


def _cube_with_holes() -> trimesh.Trimesh:
    """A 40 mm cube with two holes a few millimetres across (2 faces removed)."""
    box = trimesh.creation.box(extents=(40, 40, 40))
    for _ in range(4):
        box = box.subdivide()
    keep = np.ones(len(box.faces), bool)
    keep[[0, len(box.faces) // 2]] = False
    return trimesh.Trimesh(box.vertices, box.faces[keep], process=False)


def _stl(mesh: trimesh.Trimesh) -> bytes:
    buf = io.BytesIO()
    mesh.export(buf, file_type="stl")
    return buf.getvalue()


def _describe(mesh: trimesh.Trimesh) -> dict:
    welded, welded_edges = rs._weld(mesh)
    return rs.describe_openings(
        welded, capped_volume_mm3=rs._pre_repair_volume(welded), welded_edges=welded_edges,
        open_edges_as_read=rs._open_edge_count(mesh))


# ---------------------------------------------------------------------------
# welding and the diagnosis
# ---------------------------------------------------------------------------


def test_weld_joins_unsewn_faces_exactly_and_leaves_real_geometry_alone():
    unsewn = _unsewn_box()
    assert not unsewn.is_watertight and rs._open_edge_count(unsewn) > 0
    welded, closed = rs._weld(unsewn)
    assert closed == rs._open_edge_count(unsewn)
    assert welded.is_watertight
    assert welded.volume == pytest.approx(6000.0, rel=1e-6)
    assert rs._open_edge_count(unsewn) > 0, "the input is never mutated"
    # Faces 0.01 mm apart are a real gap at this tolerance: not welded.
    apart, closed = rs._weld(_unsewn_box(gap=0.01))
    assert closed == 0 and not apart.is_watertight
    # A closed mesh comes back as it is.
    cube = trimesh.creation.box(extents=[10.0] * 3)
    assert rs._weld(cube) == (cube, 0)


def test_describe_openings_names_the_kind_of_opening():
    face = _describe(_box_missing(2))
    assert face["kind"] == "face" and face["loops"] == 1
    assert face["largest_mm"] == pytest.approx(10.0) and face["part_mm"] == pytest.approx(10.0)

    gaps = _describe(_cube_with_holes())
    assert gaps["kind"] == "gaps" and gaps["loops"] == 2 and gaps["largest_mm"] < 0.25 * 40
    assert _describe(_cube_with_holes())["open_edges"] == 6

    seams = _describe(_unsewn_box())
    assert seams["kind"] == "seams" and seams["welded_edges"] == seams["open_edges"] > 0
    assert seams["open_edges_after_weld"] == 0

    sheet = trimesh.Trimesh([[0, 0, 0], [20, 0, 0], [0, 20, 0], [20, 20, 0]], [[0, 1, 2], [1, 3, 2]], process=False)
    surface = _describe(sheet)
    assert surface["kind"] == "surface" and surface["loops"] == 1

    closed = _describe(trimesh.creation.box(extents=[10.0] * 3))
    assert closed["kind"] == "none" and closed["open_edges"] == 0 and closed["loops"] == 0


def test_every_outcome_has_one_plain_sentence():
    face = {"kind": "face", "loops": 3, "largest_mm": 20.0, "open_edges": 945, "open_edges_after_weld": 663}
    out, text = rs.repair_outcome(True, {"openings": face, "volume_change_pct": 0.1, "volume_warning": None})
    assert out == "repaired"
    assert text == "Closed the missing face (an opening 20 mm across) and 2 smaller openings. The volume changed +0.1%."
    out, text = rs.repair_outcome(True, {"openings": face, "volume_change_pct": 10.4, "volume_warning": "..."})
    assert out == "closed_changed" and "+10.4%" in text and "bore, hole or pocket" in text
    out, text = rs.repair_outcome(True, {"openings": face, "volume_change_pct": None, "volume_warning": "..."})
    assert out == "closed_changed" and "couldn't be measured" in text
    out, text = rs.repair_outcome(False, {"openings": face, "openings_after": {"faces": 900, "open_edges": 40, "loops": 1, "largest_mm": 6.0}})
    assert out == "partly"
    assert text.startswith("Partly closed: 623 of 663 open edges closed, 1 opening is still open (the largest 6 mm across).")
    out, text = rs.repair_outcome(False, {"openings": face, "openings_after": None})
    assert out == "not_repaired" and text.startswith("A face is missing (an opening 20 mm across)")
    out, text = rs.repair_outcome(False, {"openings": {"kind": "surface", "loops": 1, "largest_mm": 20.0}})
    assert out == "not_repaired" and "surface with no thickness" in text
    out, text = rs.repair_outcome(False, {"openings": face, "timed_out": True, "reason": "Repair timed out after 30 s."})
    assert (out, text) == ("not_repaired", "Repair timed out after 30 s.")
    out, text = rs.repair_outcome(True, {"openings": {"kind": "seams", "loops": 0}, "volume_change_pct": 0.0, "volume_warning": None})
    assert text == "Closed the faces that touched but weren't joined. The volume changed +0.0%."
    sized = {**face, "sizes_mm": [20.0, 6.0, 6.0]}
    _, text = rs.repair_outcome(True, {"openings": sized, "volume_change_pct": 0.1, "volume_warning": None})
    assert text.startswith("Closed the missing face (an opening 20 mm across) and 2 smaller openings (6 mm, 6 mm).")
    assert rs.repair_outcome(False, {"openings": {"kind": "none"}, "not_needed": True}) == (
        "not_needed", "Already a closed solid: nothing to repair.")


def _fake_analysis(*args, **kwargs):
    return {"overall_verdict": "fail", "geometry": {"is_watertight": False}}


@pytest.mark.asyncio
async def test_the_open_bored_block_closes_without_filling_its_bore(monkeypatch):
    """Welded first, the repair caps the missing top and keeps the 6 mm bore."""
    from src.services import analysis_service

    monkeypatch.setattr(analysis_service, "run_analysis", AsyncMock(side_effect=_fake_analysis))
    result = await rs.repair_mesh(
        file_bytes=OPEN_BORED_BLOCK.read_bytes(), filename=OPEN_BORED_BLOCK.name,
        processes=None, rule_pack=None, user=MagicMock(), session=AsyncMock())
    assert result["repair_applied"] is True and result["outcome"] == "repaired"
    d = result["repair_details"]
    assert d["original_volume_mm3"] == pytest.approx(BORED_BLOCK_MM3, rel=1e-3)
    assert d["repaired_volume_mm3"] == pytest.approx(BORED_BLOCK_MM3, rel=2e-3), "the bore stays open"
    assert abs(d["volume_change_pct"]) < 0.2 and d["volume_warning"] is None
    o = d["openings"]
    assert o["kind"] == "face" and o["largest_mm"] == pytest.approx(20.0)
    assert o["open_edges"] == 945 and o["welded_edges"] > 0
    assert result["summary"].startswith("Closed the missing face (an opening 20 mm across)")
    assert result["repair_verification"]["checks_used"] == 0
    assert result["repair_verification"]["download_filename"] == "open-bored-block-mm-repaired.stl"


@pytest.mark.asyncio
async def test_a_surface_ends_with_why_nothing_was_made(monkeypatch):
    from src.services import analysis_service

    monkeypatch.setattr(analysis_service, "run_analysis", AsyncMock(side_effect=_fake_analysis))
    raw = (ASSETS / "open-plane-mm.iges").read_bytes()
    result = await rs.repair_mesh(file_bytes=raw, filename="open-plane-mm.iges", processes=None,
                                  rule_pack=None, user=MagicMock(), session=AsyncMock())
    assert result["repair_applied"] is False and result["outcome"] == "not_repaired"
    assert result["repair_details"]["openings"]["kind"] == "surface"
    assert "surface with no thickness" in result["summary"]
    assert result["repair_details"]["reason"] == result["summary"]
    assert result["repaired_file_b64"] is None


# ---------------------------------------------------------------------------
# POST /parts/{mesh_hash}/repair
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "objects"))
    monkeypatch.setenv("ADMISSION_DISABLED", "1")
    return tmp_path


@pytest.fixture(autouse=True)
def _memberships(monkeypatch):
    async def lookup(user_id: int):
        return USERS.get(user_id)

    monkeypatch.setattr("src.auth.rbac.lookup_org_membership", lookup)


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


def _app(user_id: int | None, *, free_limits: bool = False) -> FastAPI:
    from src.api.part_fixes import router
    from src.auth import free_tool_limits
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/v1/parts")
    if user_id is not None:
        app.dependency_overrides[require_api_key] = lambda: AuthedUser(
            user_id=user_id, api_key_id=0, key_prefix="session", role="analyst")
    if not free_limits:
        for dependency in free_tool_limits.ALL:
            app.dependency_overrides[dependency] = lambda: None

    async def _session():
        yield _fake_session()

    app.dependency_overrides[get_db_session] = _session
    return app


def test_repair_a_kept_part_end_to_end(store):
    raw = _stl(_box_missing(2))
    digest = _save(ORG_A, "bracket.stl", raw)
    client = TestClient(_app(1))
    r = client.post(f"/api/v1/parts/{digest}/repair?with_cost=false")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["repair_applied"] is True and body["outcome"] == "repaired"
    assert body["summary"] == "Closed the missing face (an opening 10 mm across). The volume changed +0.0%."
    assert body["source"] == {"mesh_hash": digest, "filename": "part.stl", "format": "stl", "bytes": len(raw)}
    assert body["repair_verification"]["checks_used"] == 0
    assert body["repair_verification"]["original_sha256"] == digest
    fixed = body["repaired"]
    fixed_hash = fixed["mesh_hash"]
    assert fixed_hash != digest and fixed["is_watertight"] is True
    assert fixed["filename"] == "part-repaired.stl" and fixed["volume_mm3"] == pytest.approx(1000.0)
    assert body["lineage"]["parent_mesh_hash"] == digest and body["lineage"]["fix"] == "mesh_repair"
    assert body["prices"] is None

    # The copy is downloadable and is the bytes the repair made; the original is not served.
    dl = client.get(body["download"]["url"])
    assert dl.status_code == 200
    assert hashlib.sha256(dl.content).hexdigest() == fixed_hash == body["repair_verification"]["repaired_sha256"]
    assert 'filename="part-repaired.stl"' in dl.headers["content-disposition"]
    assert base64.b64decode(body["repaired_file_b64"]) == dl.content
    assert client.get(f"/api/v1/parts/{digest}/fixed-file").status_code == 404

    # The original stays as it was; the copy knows its parent.
    from src.services.source_artifact_service import read_source_artifact
    from src.services import cad_fix_service

    kept, _ = asyncio.run(read_source_artifact(ORG_A, digest))
    assert kept == raw
    child = client.get(f"/api/v1/parts/{fixed_hash}/fixes").json()
    assert child["derived_from"]["parent_mesh_hash"] == digest
    record = asyncio.run(cad_fix_service._get_json(cad_fix_service._record_key(ORG_A, digest, "fixes/mesh_repair.json")))
    assert record["outcome"] == "repaired" and record["fixed_mesh_hash"] == fixed_hash


def test_a_closed_part_has_nothing_to_repair_and_no_copy_is_made(store):
    digest = _save(ORG_A, "cube.stl", _stl(trimesh.creation.box(extents=[10.0] * 3)))
    body = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/repair?with_cost=false").json()
    assert body["outcome"] == "not_needed" and body["repair_applied"] is False
    assert body["summary"] == "Already a closed solid: nothing to repair."
    assert body["repaired"] is None and body["download"] is None


def test_a_kept_part_that_cannot_be_closed_says_why_and_makes_nothing(store, monkeypatch):
    raw = _stl(_box_missing(2))
    digest = _save(ORG_A, "bracket.stl", raw)
    still_open = _box_missing(1)
    monkeypatch.setattr(rs, "_do_repair", lambda mesh: (still_open, "pymeshfix", 0))
    body = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/repair?with_cost=false").json()
    assert body["repair_applied"] is False and body["outcome"] == "partly"
    assert body["summary"].startswith("Partly closed: 1 of 4 open edges closed")
    assert body["repaired"] is None and body["download"] is None and body["repaired_file_b64"] is None
    assert body["repair_details"]["reason"] == body["summary"]


def test_repair_prices_the_repaired_copy_only(store):
    digest = _save(ORG_A, "bracket.stl", _stl(_box_missing(2, size=20.0)))
    r = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/repair?qty=10,1000&material_class=aluminum")
    assert r.status_code == 200, r.text
    prices = r.json()["prices"]
    assert prices["quantities"] == [10, 1000] and prices["basis"] == "request"
    assert prices["material_class"] == "aluminum" and prices["before"] is None
    assert [p["qty"] for p in prices["after"]] == [10, 1000]
    assert any(p["unit_cost_usd"] for p in prices["after"]), "something can make the repaired cube"


def test_repair_auth_org_scoping_and_request_errors(store, monkeypatch):
    digest = _save(ORG_A, "bracket.stl", _stl(_box_missing(2)))
    path = f"/api/v1/parts/{digest}/repair?with_cost=false"
    assert TestClient(_app(None)).post(path).status_code == 401
    assert TestClient(_app(99)).post(path).status_code == 403
    # Another org's hash is the same 404 as a part never stored, or a bad hash.
    assert TestClient(_app(2)).post(path).status_code == 404
    assert TestClient(_app(1)).post(path.replace(digest, "0" * 64)).status_code == 404
    assert TestClient(_app(1)).post("/api/v1/parts/not-a-hash/repair").status_code == 404
    # A viewer can't add a part.
    assert TestClient(_app(3)).post(path).status_code == 403
    client = TestClient(_app(1))
    assert client.post(path + "&rule_pack=nope").status_code == 400
    assert client.post(path + "&material_class=unobtainium").status_code == 400
    # The upload's limits apply to the kept file too.
    monkeypatch.setenv("REPAIR_MAX_FACES", "4")
    assert client.post(path).status_code == 413
    monkeypatch.delenv("REPAIR_MAX_FACES")
    from src.api import routes

    monkeypatch.setattr(routes, "_max_upload_bytes", lambda: 100)
    r = client.post(path)
    assert r.status_code == 413 and "limit" in r.json()["detail"]


def test_repair_needs_no_paid_plan_uses_no_check_and_has_the_free_ceiling(store, monkeypatch):
    from slowapi import Limiter

    from src.api.part_fixes import router
    from src.auth import free_tool_limits, validation_caps
    from src.auth.org_limits import enforce_org_limits
    from src.auth.validation_caps import enforce_validation_caps, require_paid_access

    def calls(dependant):
        for d in dependant.dependencies:
            yield d.call
            yield from calls(d)

    route = next(r for r in router.routes if r.path == "/{mesh_hash}/repair")
    found = set(calls(route.dependant))
    assert require_paid_access not in found
    assert enforce_validation_caps not in found and enforce_org_limits not in found
    assert free_tool_limits.limit_free_repair in found

    # A free trial account repairs; past the ceiling it gets the plain 429.
    monkeypatch.setattr(free_tool_limits, "limiter", Limiter(key_func=lambda: "t", storage_uri="memory://", enabled=True))
    monkeypatch.setenv("FREE_REPAIR_LIMIT", "1/hour")

    async def trial(user_id):
        return "trial"

    monkeypatch.setattr(validation_caps, "effective_plan", trial)
    digest = _save(ORG_A, "bracket.stl", _stl(_box_missing(2)))
    client = TestClient(_app(1, free_limits=True))
    first = client.post(f"/api/v1/parts/{digest}/repair?with_cost=false")
    assert first.status_code == 200 and first.json()["outcome"] == "repaired", first.text
    second = client.post(f"/api/v1/parts/{digest}/repair?with_cost=false")
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "free_tool_limit" and second.json()["detail"]["tool"] == "repair"

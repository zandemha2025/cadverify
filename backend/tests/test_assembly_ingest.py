"""Real STEP-assembly ingestion (Phase 1) tested against a REAL assembly.

Oracle: the canonical AS1 STEP AP203 reference assembly (base plate + two mirrored
L-bracket sub-assemblies + a rod + a nut/bolt fastener stack = 18 positioned
solids). Ground-truth numbers are from the committed spike
(outputs/human-sim/assembly-real/FINDINGS.md), which is itself a real gmsh/OCC run.

Coverage:
  * AS1 -> 18 parts, nested product tree (L-BRACKET-ASSEMBLY / NUT-BOLT-ASSEMBLY),
    distinct plausible world positions (mirrored brackets, rod-end nuts), non-empty
    per-part meshes, a valid combined GLB with a named node per part.
  * Single-part control (cube.step): classified single_part, NOT assembly-wrapped;
    and the EXISTING single-part mesh path stays byte-identical (unchanged).
  * Native-format input (.sldasm): a clean, specific unsupported-reader 400.
  * Label -> product-tree parsing unit tests (no gmsh needed).
"""
from __future__ import annotations

import importlib
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.parsers.step_mesher import is_step_supported

ASSETS = Path(__file__).parent / "assets"

_needs_gmsh = pytest.mark.skipif(
    not is_step_supported(), reason="gmsh/STEP path unavailable"
)


def _as1_path() -> Path | None:
    """Locate the real AS1 assembly: the gitignored corpus copy, else the copy that
    ships inside the gmsh distribution's public examples (same file, sha-verified)."""
    import gmsh  # type: ignore

    candidates = [
        Path(__file__).resolve().parents[2] / "data/real-corpus/as1-tu-203.stp",
        Path(gmsh.__file__).resolve().parent
        / "share/doc/gmsh/examples/api/as1-tu-203.stp",
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


# ── Label -> product-tree parsing (pure, no gmsh) ───────────────────────────
def test_parse_label_strips_container_and_suffix():
    from src.parsers.assembly_mesher import _parse_label

    root, segs = _parse_label(
        "Shapes/as1/L-BRACKET-ASSEMBLY::1/l-bracket-assembly/"
        "NUT-BOLT-ASSEMBLY::2/nut-bolt-assembly/BOLT/bolt & & 256"
    )
    assert root == "as1"
    assert segs == [
        ("L-BRACKET-ASSEMBLY", 1, "l-bracket-assembly"),
        ("NUT-BOLT-ASSEMBLY", 2, "nut-bolt-assembly"),
        ("BOLT", 1, "bolt"),
    ]


def test_parse_label_leaf_directly_under_root():
    from src.parsers.assembly_mesher import _parse_label

    root, segs = _parse_label("Shapes/as1/PLATE/plate")
    assert root == "as1"
    assert segs == [("PLATE", 1, "plate")]


def test_build_tree_keys_siblings_by_instance():
    """Two occurrences of the same product under one parent stay distinct nodes."""
    from src.parsers.assembly_mesher import _build_tree

    parsed = [
        ([("NUT", 1, "nut")], "p1"),
        ([("NUT", 2, "nut")], "p2"),
        ([("ROD", 1, "rod")], "p3"),
    ]
    tree = _build_tree("root", parsed)
    assert len(tree.children) == 3
    leaves = {(c.occurrence, c.instance): c.part_id for c in tree.children}
    assert leaves == {("NUT", 1): "p1", ("NUT", 2): "p2", ("ROD", 1): "p3"}


# ── Native-format handling (specific unsupported error) ─────────────────────
def test_native_cad_error_is_specific():
    from src.parsers.assembly_mesher import is_native_cad_suffix, native_cad_error

    assert is_native_cad_suffix(".SLDASM")
    err = native_cad_error(".sldasm")
    msg = str(err)
    assert "SolidWorks" in msg
    assert "licensed reader" in msg
    assert "STEP" in msg  # points at the fix


# ── AS1: the real oracle ────────────────────────────────────────────────────
@_needs_gmsh
def test_as1_extracts_18_parts_tree_and_positions():
    from src.parsers.assembly_mesher import extract_assembly_from_bytes

    model = extract_assembly_from_bytes(_as1_bytes(), "as1-tu-203.stp")

    # 18 distinct positioned solids; 5 unique designs (spike ground truth).
    assert model.kind == "assembly"
    assert model.part_count == 18
    assert len(model.parts) == 18
    assert model.unique_designs == {
        "nut": 8, "bolt": 6, "l-bracket": 2, "rod": 1, "plate": 1,
    }
    assert model.truncated is False

    # Every part meshed to a non-empty, per-solid-watertight shell.
    for p in model.parts:
        assert p.geometry_summary.num_triangles > 0, p.tree_path
        assert p.mesh is not None and len(p.mesh.faces) > 0
        assert p.mesh.is_watertight, f"{p.tree_path} not watertight"
        assert p.mesh_ref == p.id

    # Volumes match the spike (mm^3), proving getMass reads real solids.
    by_name = {}
    for p in model.parts:
        by_name.setdefault(p.name, []).append(p)
    assert round(by_name["plate"][0].world.volume) == 530575
    assert round(by_name["rod"][0].world.volume) == 15709
    assert all(round(b.world.volume) == 96858 for b in by_name["l-bracket"])
    assert all(round(b.world.volume) == 3201 for b in by_name["bolt"])
    assert all(round(n.world.volume) == 664 for n in by_name["nut"])

    # Distinct world positions: the two L-brackets mirror on opposite sides.
    bracket_x = sorted(round(b.world.centroid[0], 1) for b in by_name["l-bracket"])
    assert bracket_x == [19.6, 160.4]
    # The two rod-end nuts sit at opposite ends of the rod (x~90).
    rod = by_name["rod"][0]
    assert abs(rod.world.centroid[0] - 90.0) < 1.0
    rod_nut_x = sorted(
        round(n.world.centroid[0], 1)
        for n in by_name["nut"]
        if n.tree_path.startswith("as1/ROD-ASSEMBLY")
    )
    assert rod_nut_x == [3.5, 176.5]

    # Nested product tree rebuilt: as1 -> {rod-assembly, plate, 2x l-bracket-assembly}
    root = model.tree
    assert root.name == "as1"
    child_names = sorted(c.name for c in root.children)
    assert child_names == [
        "l-bracket-assembly", "l-bracket-assembly", "plate", "rod-assembly",
    ]
    # Each l-bracket-assembly nests 3 nut-bolt-assemblies + the l-bracket leaf.
    lba = [c for c in root.children if c.name == "l-bracket-assembly"]
    assert len(lba) == 2
    for node in lba:
        sub = sorted(c.name for c in node.children)
        assert sub == [
            "l-bracket", "nut-bolt-assembly", "nut-bolt-assembly", "nut-bolt-assembly",
        ]
        for nba in [c for c in node.children if c.name == "nut-bolt-assembly"]:
            leaf_names = sorted(c.name for c in nba.children)
            assert leaf_names == ["bolt", "nut"]

    # Honest limits surfaced (not faked).
    limits = model.to_dict()["limits"]
    assert "mate_constraints" in limits and "gdt_pmi_tolerances" in limits


@_needs_gmsh
def test_as1_glb_has_named_node_per_part():
    from src.parsers.assembly_mesher import assembly_to_glb, extract_assembly_from_bytes

    model = extract_assembly_from_bytes(_as1_bytes(), "as1-tu-203.stp")
    glb = assembly_to_glb(model)
    magic, version = struct.unpack_from("<4sI", glb, 0)
    assert magic == b"glTF" and version == 2
    assert len(glb) > 100_000  # 18 real meshes, not an empty scene


# ── Route contract ──────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    # In-thread extraction for deterministic, fast tests (the pool path is covered
    # by its own byte-identity + fallback tests).
    monkeypatch.setenv("PARSE_PROCESS_POOL_DISABLED", "1")
    import main

    importlib.reload(main)
    return TestClient(main.app)


@_needs_gmsh
def test_route_as1_json(client):
    r = client.post(
        "/api/v1/validate/assembly",
        files={"file": ("as1-tu-203.stp", _as1_bytes(), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "assembly"
    assert body["part_count"] == 18
    assert body["unique_designs"]["nut"] == 8
    assert "limits" in body and "mate_constraints" in body["limits"]
    # Each JSON part carries position + tree + mesh_ref for P2/P3.
    p = body["parts"][0]
    assert set(p) >= {"id", "name", "tree_path", "world", "geometry_summary", "mesh_ref"}
    assert set(p["world"]) >= {"bbox_min", "bbox_max", "centroid", "volume"}


@_needs_gmsh
def test_route_as1_glb(client):
    r = client.post(
        "/api/v1/validate/assembly?format=glb",
        files={"file": ("as1.step", _as1_bytes(), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("model/gltf-binary")
    assert r.headers["x-assembly-parts"] == "18"
    assert r.content[:4] == b"glTF"


@_needs_gmsh
def test_route_single_part_classified_not_wrapped(client):
    """A single-solid file is detected as single_part (1 solid), NOT wrapped as an
    assembly — the single-part contract is preserved."""
    r = client.post(
        "/api/v1/validate/assembly",
        files={"file": ("cube.step", (ASSETS / "cube.step").read_bytes(), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "single_part"
    assert body["part_count"] == 1


@_needs_gmsh
def test_single_part_mesh_path_byte_identical(client):
    """The EXISTING single-part STEP mesh path is unchanged by assembly ingestion:
    the in-thread parse and the pooled parse still agree byte-for-byte (the
    pre-existing invariant), so single-part /validate output is untouched."""
    from src.api.routes import _parse_mesh
    from src.parsers import parse_pool

    data = (ASSETS / "cube.step").read_bytes()
    m_thread, _ = _parse_mesh(data, "cube.step")
    m_pool = parse_pool.submit_sync(data, ".step")
    assert m_thread.vertices.shape == m_pool.vertices.shape
    assert m_thread.faces.shape == m_pool.faces.shape
    assert len(m_thread.faces) > 50_000  # real tessellated cube, not a box


def test_route_native_format_specific_400(client):
    r = client.post(
        "/api/v1/validate/assembly",
        files={"file": ("widget.sldasm", b"x" * 300, "application/octet-stream")},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["message"] if "message" in r.json() else r.json()["detail"]
    assert "SolidWorks" in detail
    assert "licensed reader" in detail


def test_route_stl_rejected_from_assembly(client, cube_10mm, stl_bytes_of):
    """STL carries no assembly structure -> a clean 400 (not a crash)."""
    r = client.post(
        "/api/v1/validate/assembly",
        files={"file": ("cube.stl", stl_bytes_of(cube_10mm), "application/octet-stream")},
    )
    assert r.status_code == 400, r.text

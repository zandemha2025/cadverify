"""STEP/STP -> trimesh.Trimesh via gmsh's embedded OpenCASCADE kernel.

This is the STEP->mesh path for DFM + cost. It produces a triangulated shell
(NOT B-rep / GD&T / PMI). gmsh embeds the OpenCASCADE kernel, reads STEP/IGES/
BREP via ``model.occ.importShapes`` and tessellates to a triangle shell which we
wrap as a ``trimesh.Trimesh``. This reuses 100% of the existing geometry /
feature / cost engine, which only needs a ``trimesh.Trimesh``.

Scope boundary (Cycle 5 §A.7):
  * IN scope: STEP/STP -> triangulated mesh -> existing DFM + cost layer.
    Single solids cost cleanly; assemblies / non-watertight bodies are refused
    downstream by the G1 geometry gate with the standard structured 400.
  * OUT of scope / BLOCKED: B-rep face graph, exact analytic surfaces, and
    GD&T / PMI / tolerance extraction from STEP AP242. Those require
    cadquery/OCP (not installable in this env). The cost numbers from a
    STEP-derived mesh carry the same absolute-band caveat as STL-derived ones.

gmsh uses a single PROCESS-GLOBAL context and is NOT thread-safe, so every entry
into the gmsh critical section is serialized by ``_GMSH_LOCK``. Meshing is
CPU-bound and can be slow on assemblies; callers MUST run this under the
analysis executor + timeout (see routes.py ``_parse_mesh_async``).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

logger = logging.getLogger("cadverify.step_mesher")

_HAS_GMSH = False
gmsh: Any = None
try:
    import gmsh as _gmsh

    gmsh = _gmsh
    _HAS_GMSH = True
except (ImportError, OSError):
    pass

# gmsh is process-global / not thread-safe; serialize across worker threads.
_GMSH_LOCK = threading.Lock()

# Tessellation tuning (mm). Curvature-adaptive, with a face budget guard.
_CURVATURE_PTS = 12.0        # min facets around a full circle
_TARGET_DIAG_SEGMENTS = 200  # MeshSizeMax ~ bbox_diagonal / this
_MIN_SIZE_MM = 0.05          # floor so tiny parts still tessellate
_MAX_SIZE_MM = 50.0          # ceiling so huge parts don't vanish

# ── Fitting the analysis budget ──────────────────────────────────────────
# The engine decimates any mesh over MAX_ANALYSIS_FACES (vertex clustering),
# which blurs the exact geometry the checks measure: small fillets read as
# sharp again and wall thickness becomes unavailable. A B-rep can instead be
# re-tessellated to fit. Only meshes over the budget are touched; every part
# under it keeps its first-pass mesh byte for byte.
#
# Why they go over: gmsh grows planar-face triangles from the size of their
# boundary edges (Mesh.MeshSizeExtendFromBoundary). A 0.5 mm fillet along a
# 120 mm edge has ~0.26 mm boundary segments, so the whole adjoining wall is
# meshed at that size: the 120 x 80 x 40 mm Design Studio enclosure goes from
# 212,526 faces to 672,924 with 0.5 mm inside fillets, 98% of them on its flat
# walls. Pass 2 stops that propagation and keeps everything else (curvature
# sizing on curved faces, MeshSizeMax on flat ones): with 1 mm fillets the
# enclosure meshes to 218,356 faces instead of 291,482, the same flat-wall
# sampling as its unfilleted self (with 0.5 mm, 231,636 instead of 672,924 --
# but that first pass alone takes ~25 s, past the time cap below, so that part
# stays as it was).
# Pass 2 runs only when flat faces really are inflated (_flat_inflation), so a
# part that is simply big at the default size goes straight to coarsening:
# MeshSizeMax grows (flat faces only; curved faces stay curvature-sized) by at
# most _FIT_MAX_COARSEN in all; past that the engine's decimation applies as
# before.
_FIT_TARGET = 0.9            # coarsening target, as a fraction of the budget
_FIT_MAX_COARSEN = 2.0       # MeshSizeMax may grow to at most 2x (diag / 100)
_FIT_INFLATED = 1.2          # flat faces this much denser than asked: pass 2
#
# Predicted over the budget: thin-walled parts. Flat faces at diag / 200 make
# a 40 x 40 x 30 mm open box with 0.5 mm walls 286,290 triangles; that first
# pass alone took ~28 s, past the refit time cap, so it went to the engine's
# vertex-clustering decimation, whose grid is coarser than the 0.5 mm walls:
# the walls disappeared and every thin-wall check passed. The B-rep tells the
# count before meshing (every face's area over the triangle size; curvature
# and boundary refinement only add to it). When that is clearly over the
# budget, the first pass would be over it anyway and is skipped: flat faces and
# the straight edges between them are meshed at diag / _FLAT_DIAG_SEGMENTS
# (a flat face needs no interior refinement to be exact), curved faces keep
# their curvature sizing under the usual MeshSizeMax. The open box meshes to
# 3,726 triangles in under a second with its walls intact. Parts predicted
# under the budget never take this path, so their first pass stays byte for byte.
_PREDICT_OVER = 1.05         # predicted first pass this far over the budget: skip it
_FLAT_DIAG_SEGMENTS = 20     # flat faces in that case: diag / this (10x the usual size)


def _fit_budget_enabled() -> bool:
    """STEP_MESH_FIT_ANALYSIS_BUDGET (default on). Off = first-pass mesh always."""
    return os.getenv("STEP_MESH_FIT_ANALYSIS_BUDGET", "1").strip().lower() not in ("0", "false", "no", "off")


def _analysis_face_budget() -> int:
    from src.analysis.context import _max_analysis_faces

    return _max_analysis_faces()


def _triangle_count() -> int:
    return int(sum(len(tags) for tags in gmsh.model.mesh.getElements(dim=2)[1]))


def _flat_inflation(size_max: float) -> float:
    """How much denser than ``size_max`` the current mesh is on flat faces.

    1.0 means flat faces are meshed at the size asked for; the 120 x 80 x 40 mm
    enclosure reads 1.01 with sharp corners, 1.38 with 1 mm fillets and 3.2 with
    0.5 mm fillets (their small boundary segments spread over the walls).
    """
    expected = actual = 0.0
    per_tri = 0.433 * size_max * size_max  # equilateral triangle of edge size_max
    for _dim, tag in gmsh.model.getEntities(2):
        if gmsh.model.getType(2, tag) != "Plane":
            continue
        expected += float(gmsh.model.occ.getMass(2, tag)) / per_tri
        actual += sum(len(t) for t in gmsh.model.mesh.getElements(2, tag)[1])
    return actual / expected if expected > 0 else 1.0


def _predicted_faces(size_max: float) -> float:
    """Triangles a first pass at ``size_max`` makes at least: each face's area
    over an equilateral triangle of that edge (the open box: 283,941 predicted,
    286,290 made)."""
    per_tri = 0.433 * size_max * size_max
    area = sum(float(gmsh.model.occ.getMass(2, tag)) for _dim, tag in gmsh.model.getEntities(2))
    return area / per_tri if per_tri > 0 else 0.0


def _flat_coarse_sizing(size_max: float, diag: float) -> dict | None:
    """Mesh flat faces coarse and curved ones as usual, when the first pass is
    predicted clearly over the budget (see ``_PREDICT_OVER``). Returns the
    sizing record (its ``curved`` cap is what later coarsening grows), or None
    when the first pass should run as always."""
    if not _fit_budget_enabled():
        return None
    budget = _analysis_face_budget()
    predicted = _predicted_faces(size_max)
    if predicted < _PREDICT_OVER * budget:
        return None
    planes = {int(tag) for _dim, tag in gmsh.model.getEntities(2) if gmsh.model.getType(2, tag) == "Plane"}
    if not planes:
        return None
    flat_curves = set()
    for _dim, curve in gmsh.model.getEntities(1):
        if gmsh.model.getType(1, curve) != "Line":
            continue
        surfaces, _points = gmsh.model.getAdjacencies(1, curve)
        if len(surfaces) and all(int(s) in planes for s in surfaces):
            flat_curves.add(int(curve))
    flat_points = set()
    curved_points = set()
    for _dim, curve in gmsh.model.getEntities(1):
        _surfaces, points = gmsh.model.getAdjacencies(1, curve)
        (flat_points if int(curve) in flat_curves else curved_points).update(int(p) for p in points)
    flat_points -= curved_points
    coarse = max(size_max, min(diag / _FLAT_DIAG_SEGMENTS, _MAX_SIZE_MM))
    sizing = {"predicted": int(predicted), "flat_size": coarse, "curved": size_max}

    def size_at(dim, tag, _x, _y, _z, lc):
        if ((dim == 2 and tag in planes) or (dim == 1 and tag in flat_curves)
                or (dim == 0 and tag in flat_points)):
            return lc
        return min(lc, sizing["curved"])

    gmsh.option.setNumber("Mesh.MeshSizeMax", coarse)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.model.mesh.setSizeCallback(size_at)
    return sizing


def _fit_time_cap_sec() -> float:
    """Wall-clock a refit may bring one tessellation to: 80% of the pool's rung-0
    cap (the same cap the in-thread ladder is held to), so a refit never turns
    a rung that finished in time into one the pool kills."""
    from src.parsers.parse_pool import _budget_sec, _rung_caps

    return 0.8 * _rung_caps(_budget_sec(), len(_MESH_RUNGS))[0]


def _fit_to_budget(size_max: float, started: float, first_pass_sec: float,
                   flat: dict | None = None) -> dict | None:
    """Re-mesh the loaded model until it fits the analysis budget.

    Called after the first ``generate(2)``. Returns None when the first pass
    already fits (nothing changed), else a record of the passes for logging.
    Pass 2 runs only when flat faces are inflated by their boundaries; the
    coarsening passes then grow MeshSizeMax (at most ``_FIT_MAX_COARSEN`` in
    all). The last pass has the fewest triangles and is the one kept. A pass
    whose estimated time (the first pass's, scaled by triangle count) would
    run past ``_fit_time_cap_sec`` is not started: the part then keeps its
    first-pass mesh and the engine decimates it, as before.
    """
    budget = _analysis_face_budget()
    count = _triangle_count()
    if flat is not None:
        return _fit_flat_coarse(size_max, started, first_pass_sec, flat, budget, count)
    if count <= budget or not _fit_budget_enabled():
        return None
    first = count
    cap = _fit_time_cap_sec()

    def affordable(expected_faces: float) -> bool:
        estimate = first_pass_sec * expected_faces / max(first, 1)
        return (time.perf_counter() - started) + estimate <= cap

    inflation = _flat_inflation(size_max)
    passes = [{"pass": 1, "faces": count, "size_max": size_max, "extend_from_boundary": 1,
               "flat_inflation": round(inflation, 2), "seconds": round(first_pass_sec, 2)}]
    record = {"budget": budget, "passes": passes, "fits": False}
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    if inflation > _FIT_INFLATED:
        if not affordable(first / inflation):
            record["stopped"] = "time"
            return record
        gmsh.model.mesh.clear()
        gmsh.model.mesh.generate(2)
        count = _triangle_count()
        passes.append({"pass": len(passes) + 1, "faces": count, "size_max": size_max,
                       "extend_from_boundary": 0})
    size = size_max
    while count > budget and size < _FIT_MAX_COARSEN * size_max - 1e-12:
        if not affordable(_FIT_TARGET * budget):
            record["stopped"] = "time"
            break
        factor = max(1.05, (count / (_FIT_TARGET * budget)) ** 0.5)
        size = min(size * factor, _FIT_MAX_COARSEN * size_max)
        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.model.mesh.clear()
        gmsh.model.mesh.generate(2)
        count = _triangle_count()
        passes.append({"pass": len(passes) + 1, "faces": count, "size_max": size,
                       "extend_from_boundary": 0})
    record["fits"] = count <= budget
    return record


def _fit_flat_coarse(size_max: float, started: float, first_pass_sec: float, flat: dict,
                     budget: int, count: int) -> dict:
    """The flat-coarse pass is meshed; if curved faces alone still put it over
    the budget, grow their size cap (at most ``_FIT_MAX_COARSEN``) under the
    same time cap as any refit. Always returns the record, so the log says
    which path a part took."""
    first = count
    cap = _fit_time_cap_sec()
    passes = [{"pass": 1, "faces": count, "size_max": size_max, "flat_size": flat["flat_size"],
               "predicted_first_pass": flat["predicted"], "extend_from_boundary": 0,
               "seconds": round(first_pass_sec, 2)}]
    record = {"budget": budget, "passes": passes, "fits": False, "flat_coarse": True}
    size = size_max
    while count > budget and size < _FIT_MAX_COARSEN * size_max - 1e-12:
        estimate = first_pass_sec * _FIT_TARGET * budget / max(first, 1)
        if (time.perf_counter() - started) + estimate > cap:
            record["stopped"] = "time"
            break
        factor = max(1.05, (count / (_FIT_TARGET * budget)) ** 0.5)
        size = min(size * factor, _FIT_MAX_COARSEN * size_max)
        flat["curved"] = size
        gmsh.model.mesh.clear()
        gmsh.model.mesh.generate(2)
        count = _triangle_count()
        passes.append({"pass": len(passes) + 1, "faces": count, "size_max": size,
                       "flat_size": flat["flat_size"], "extend_from_boundary": 0})
    record["fits"] = count <= budget
    return record


# ── Retry ladder ──────────────────────────────────────────────────────────
# ~19% of real NIST STEP parts hit gmsh's "Impossible to mesh periodic surface N"
# on certain OCC geometries, which aborts the DEFAULT (curvature-adaptive) 2D
# mesher. gmsh 4.15 is the only STEP mesher available, so recovery must stay
# WITHIN gmsh: on failure we re-import the shape and retry with progressively more
# robust settings.
#
# Each rung is (name, mesh_algorithm | None, curvature_pts, occ_heal).
#   * RUNG 0 == PRIMARY and is BYTE-IDENTICAL to the historical single-attempt
#     path (gmsh's default 2D algorithm + curvature refinement). It runs first and
#     unchanged, so every part that already meshes stays exactly as before. The
#     retry rungs engage ONLY after it fails.
#   * Rung 1 (MeshAdapt, curvature OFF): MeshAdapt (Mesh.Algorithm=1) is gmsh's
#     most robust 2D algorithm for tricky/periodic surfaces. Curvature refinement
#     is precisely what it chokes on for these B-reps (MeshAdapt WITH curvature
#     errors — and can segfault — on the same parts), so we mesh uniformly at
#     MeshSizeMax: coarser, but a valid closed shell. This rung recovers the known
#     periodic-surface failures (nist_ctc_02/04/05) to watertight shells in <10s.
#     Some gmsh/platform combinations do not raise on the primary rung; they
#     return a non-watertight shell instead. The ladder treats that as a fallback
#     candidate and still advances to this recovery rung.
#   * Rung 2 (+ OCC shape healing): last resort for degenerate B-reps — OCC auto-
#     fix / sew is applied BEFORE import. Coarser still and not guaranteed
#     watertight, but a non-empty shell is better than a hard failure (the
#     downstream G1 gate refuses a non-watertight shell with a clean 400).
_MESH_RUNGS = (
    ("primary", None, _CURVATURE_PTS, False),
    ("meshadapt-uniform", 1, 0.0, False),
    ("meshadapt-uniform-occheal", 1, 0.0, True),
)

# OCC shape-healing options — must be set BEFORE importShapes so OCC applies them
# while reading the B-rep. Only engaged by the final retry rung.
_OCC_HEAL_OPTS = (
    "Geometry.OCCAutoFix",
    "Geometry.OCCFixDegenerated",
    "Geometry.OCCFixSmallEdges",
    "Geometry.OCCFixSmallFaces",
    "Geometry.OCCSewFaces",
)


class _StepReadError(Exception):
    """OCC could not READ the shape (vs. could not MESH it). Non-retryable: a
    different mesh algorithm cannot fix an unreadable/invalid STEP file."""


class _EmptyMeshError(Exception):
    """A rung tessellated the (readable) shape but produced an empty mesh.
    Retryable: a more robust rung may still yield a non-empty shell."""


def _shell_defect_count(mesh: trimesh.Trimesh) -> int:
    """Count unique edges that are not shared by exactly two triangles.

    Used only to rank non-watertight fallback shells. A lower count is a less
    broken shell; a watertight result never reaches this ranking because it wins
    the ladder immediately.
    """
    inverse = np.asarray(mesh.edges_unique_inverse, dtype=np.int64).reshape(-1)
    if inverse.size == 0:
        return 2**63 - 1
    incidence = np.bincount(inverse)
    return int(np.count_nonzero(incidence != 2))


def _prefer_open_shell(
    current: trimesh.Trimesh | None,
    candidate: trimesh.Trimesh,
) -> trimesh.Trimesh:
    """Keep the least-defective open shell as the downstream G1 fallback."""
    if current is None:
        return candidate
    if _shell_defect_count(candidate) < _shell_defect_count(current):
        return candidate
    return current


def is_step_supported() -> bool:
    """True iff the gmsh STEP path is importable."""
    return _HAS_GMSH


def _configure_cad_import(path: str) -> None:
    # A cold IGES reader cannot set OCC's not-yet-initialized target-unit
    # registry. Its native default already converts file units to millimeters;
    # setting an explicit target here rejects valid IGES before reading it.
    iges = Path(path).suffix.lower() in (".iges", ".igs")
    target = "" if iges else "MM"
    gmsh.option.setString("Geometry.OCCTargetUnit", target)
    if iges:
        # IGES commonly supplies separate faces. Let OCC sew coincident edges
        # at its existing tolerance and form solids only from closed shells.
        gmsh.option.setNumber("Geometry.OCCSewFaces", 1)
        gmsh.option.setNumber("Geometry.OCCMakeSolids", 1)


def _iges_3d_preference(data: bytes) -> bytes | None:
    """Prefer supplied 3D curves only where IGES declares no 2D/3D preference.

    Change only the type-142 preference byte, never coordinates or topology.
    Explicit 2D preferences and entities missing either representation stay put.
    """
    import re

    lines = data.splitlines(keepends=True)
    global_data = b"".join(line[:72] for line in lines if line[72:73] == b"G").lstrip()
    # ponytail: this recovery handles the standard delimiters; custom delimiters
    # keep the native reader's result until a real fixture justifies extending it.
    if not global_data.startswith((b",,", b",1H;,", b"1H,,,", b"1H,,1H;,")):
        return None
    try:
        parameters = {int(line[73:80]): i for i, line in enumerate(lines) if line[72:73] == b"P"}
        changed = False
        for i, line in enumerate(lines):
            if line[72:73] != b"D" or int(line[73:80]) % 2 == 0 or int(line[:8]) != 142:
                continue
            start, count = int(line[8:16]), int(lines[i + 1][24:32])
            if count <= 0 or count > len(parameters):
                continue
            records = [parameters[n] for n in range(start, start + count)]
            if any(int(lines[n][64:72]) != int(line[73:80]) for n in records):
                continue
            payload = b"".join(lines[n][:64] for n in records)
            match = re.fullmatch(rb"\s*142\s*,\s*\d+\s*,\s*[1-9]\d*\s*,\s*[1-9]\d*\s*,\s*[1-9]\d*\s*,\s*([03])\s*;\s*", payload)
            if match:
                row, column = divmod(match.start(1), 64)
                index = records[row]
                lines[index] = lines[index][:column] + b"2" + lines[index][column + 1:]
                changed = True
        return b"".join(lines) if changed else None
    except (ValueError, IndexError, KeyError):
        return None  # The native reader owns malformed or unsupported records.


def _import_cad_shapes(path: str):
    """Retry unclosed IGES using its equally preferred, supplied 3D curves."""
    import tempfile

    empty_model = not gmsh.model.occ.getEntities()
    roots = gmsh.model.occ.importShapes(path)
    if not empty_model or Path(path).suffix.lower() not in {".iges", ".igs"} or gmsh.model.occ.getEntities(3):
        return roots
    alternate = _iges_3d_preference(Path(path).read_bytes())
    if alternate is None:
        return roots
    with tempfile.NamedTemporaryFile(suffix=".iges", mode="w+b") as tmp:
        os.chmod(tmp.name, 0o600)
        tmp.write(alternate)
        tmp.flush()
        gmsh.model.occ.remove(roots, recursive=True)
        try:
            recovered = gmsh.model.occ.importShapes(tmp.name)
            if gmsh.model.occ.getEntities(3):
                logger.info("Recovered IGES solid using its supplied 3D curves at unchanged tolerance")
                return recovered
        except Exception:
            logger.warning("IGES 3D-curve retry failed; retaining native import")
        gmsh.model.occ.remove(gmsh.model.occ.getEntities(), recursive=True)
        return gmsh.model.occ.importShapes(path)


def step_to_trimesh_from_bytes(data: bytes, filename: str = "upload.step") -> trimesh.Trimesh:
    """Parse STEP bytes -> watertight-where-possible ``trimesh.Trimesh``.

    Mirrors ``step_parser``'s temp-file discipline (0o600, guaranteed unlink).
    Raises ``ValueError`` with a SAFE, static-ish message on any parse/mesh
    failure (the route maps ``ValueError`` -> 400). Never leaks gmsh internals
    to the caller.
    """
    # AP242 may already carry standardized triangle strips/fans instead of a
    # B-rep. Native OCC import cannot read that branch, so consume the supplied
    # tessellation directly before asking gmsh to generate another one.
    from src.parsers.ap242_tessellated_parser import (
        AP242TessellationError,
        is_ap242_tessellated,
        parse_ap242_tessellated,
    )

    if is_ap242_tessellated(data):
        try:
            return parse_ap242_tessellated(data)
        except AP242TessellationError as exc:
            raise ValueError(
                "Could not read the embedded AP242 tessellated geometry."
            ) from exc

    if not _HAS_GMSH:
        raise RuntimeError("gmsh not installed")  # route maps to 501 (see A.5)

    import tempfile
    suffix = Path(filename).suffix.lower() or ".step"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w+b")
    try:
        os.chmod(tmp.name, 0o600)           # owner R/W only (IP-local discipline)
        tmp.write(data)
        tmp.flush()
        tmp.close()
        return _mesh_step_file(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass


# What the B-rep says about each triangle, kept on the mesh's metadata (same face
# order as ``mesh.faces``). Checks that measure a surface's direction (draft) read
# the CAD surface's own normal instead of a triangle's, and a finding can count
# the CAD faces it lies on (the faces a CAD tool shows) instead of triangles.
# Orientation turns rotate CAD_NORMALS_KEY with the mesh; anything that rebuilds
# the faces (decimation) drops both, and readers check the length first.
CAD_FACES_KEY = "cad_face_ids"        # (M,) int32: B-rep face index, 0..K-1
CAD_NORMALS_KEY = "cad_face_normals"  # (M, 3) float32: the surface's unit normal at the triangle
CAD_FACE_COUNT_KEY = "cad_face_count"  # K: B-rep faces in the solid
# Per B-rep face (index 0..K-1), for cylinders: {"radius_mm", "arc_deg", "length_mm"}
# (an inside corner rounded R0.5 over 90° and 20 mm deep); None for other faces.
CAD_FACE_SHAPES_KEY = "cad_face_shapes"
# The last tessellation's B-rep data, read back under ``_GMSH_LOCK`` by ``_run_rung``
# (``_tessellate_once`` keeps its two-array return).
_LAST_CAD: dict = {}


def _cylinder_shape(tag: int) -> dict | None:
    """A B-rep cylinder's radius, the arc it spans and its length (frame-free numbers)."""
    if gmsh.model.getType(2, tag) != "Cylinder":
        return None
    lo, hi = gmsh.model.getParametrizationBounds(2, tag)
    curvature = gmsh.model.getCurvature(2, tag, [(lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0])
    k = float(curvature[0]) if len(curvature) else 0.0
    if not (k > 0 and np.isfinite(k)):
        return None
    return {"radius_mm": 1.0 / k, "arc_deg": float(np.degrees(abs(hi[0] - lo[0]))),
            "length_mm": float(abs(hi[1] - lo[1]))}


def _cad_face_data() -> dict | None:
    """Per-triangle B-rep face index and the surface's exact normal there.

    gmsh lists a surface's triangles entity by entity in the same order as
    ``getElements(dim=2)``, so the arrays line up with the mesh's faces. The
    normal is the B-rep surface's own (``getNormal`` at each node's parameters),
    averaged over the triangle's three nodes: a 3.0° drafted cone reads 3.0° on
    every triangle, where its facets read 2.6–3.3°. Its sign follows the surface
    parametrisation, which a draft reading (``|90° - angle from +Z|``) ignores.
    None when any surface can't be read this way (the mesh is used as before).
    """
    ids: list[np.ndarray] = []
    normals: list[np.ndarray] = []
    entities = gmsh.model.getEntities(2)
    shapes: list[dict | None] = []
    for _dim, tag in entities:
        try:
            shapes.append(_cylinder_shape(tag))
        except Exception:
            shapes.append(None)
    for index, (_dim, tag) in enumerate(entities):
        etypes, _etags, enodes = gmsh.model.mesh.getElements(2, tag)
        conn = [c for et, c in zip(etypes, enodes) if et == 2]
        if not conn:
            continue
        tri = np.concatenate(conn).astype(np.int64).reshape(-1, 3)
        node_tags, _coords, uv = gmsh.model.mesh.getNodes(2, tag, includeBoundary=True,
                                                          returnParametricCoord=True)
        if len(uv) != 2 * len(node_tags) or not len(node_tags):
            return None
        at = np.asarray(gmsh.model.getNormal(tag, uv), dtype=np.float64).reshape(-1, 3)
        order = np.argsort(node_tags)
        sorted_tags = np.asarray(node_tags, dtype=np.int64)[order]
        pos = np.searchsorted(sorted_tags, tri)
        if np.any(pos >= len(sorted_tags)) or np.any(sorted_tags[np.minimum(pos, len(sorted_tags) - 1)] != tri):
            return None
        mean = at[order[pos]].sum(axis=1)
        length = np.linalg.norm(mean, axis=1)
        if not np.all(np.isfinite(length)) or np.any(length < 1e-9):
            return None
        normals.append((mean / length[:, None]).astype(np.float32))
        ids.append(np.full(len(tri), index, dtype=np.int32))
    if not ids:
        return None
    return {CAD_FACES_KEY: np.concatenate(ids), CAD_NORMALS_KEY: np.concatenate(normals),
            CAD_FACE_COUNT_KEY: len(entities), CAD_FACE_SHAPES_KEY: shapes}


def _tessellate_once(
    path: str,
    algorithm,
    curvature_pts: float,
    heal: bool,
    *,
    target_diag_segments: int = _TARGET_DIAG_SEGMENTS,
    cad: dict | None = None,
):
    """One full gmsh initialize -> import -> generate(2) -> extract -> finalize
    cycle for a single retry rung. Returns ``(verts Nx3, faces Mx3)``.

    Raises ``_StepReadError`` if OCC cannot read the shape (non-retryable). Any
    OTHER exception means this rung failed to MESH the (readable) shape, and the
    caller advances to the next rung. MUST be called under ``_GMSH_LOCK``.

    ``algorithm=None`` leaves ``Mesh.Algorithm`` at gmsh's default; ``heal=True``
    applies OCC shape healing before import. With ``algorithm=None, curvature_pts=
    _CURVATURE_PTS, heal=False`` this issues the EXACT same gmsh calls, in the
    same order, as the historical primary path — so rung 0 output is unchanged.
    """
    # interruptible=False: skip gmsh's SIGINT handler install, which calls
    # signal.signal() and only works on the MAIN thread. The route meshes in a
    # ThreadPoolExecutor (A.5), so the default would raise "signal only works in
    # main thread of the main interpreter".
    started = time.perf_counter()
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)          # no stdout spew
        _configure_cad_import(path)
        if heal:
            for opt in _OCC_HEAL_OPTS:                        # heal BEFORE import
                gmsh.option.setNumber(opt, 1)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", curvature_pts)
        gmsh.model.add("part")
        try:
            _import_cad_shapes(path)   # STEP/IGES/BREP via OCC
            gmsh.model.occ.synchronize()
        except Exception as exc:                # OCC reader rejected the file
            raise _StepReadError(str(exc)) from exc

        # Scale-aware element budget. Product rungs use
        # ``_TARGET_DIAG_SEGMENTS``; the startup-only readiness parse supplies a
        # much coarser private value so its throwaway mesh stays bounded.
        xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
        diag = ((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2) ** 0.5
        size_max = min(max(diag / target_diag_segments, _MIN_SIZE_MM), _MAX_SIZE_MM)
        gmsh.option.setNumber("Mesh.MeshSizeMax", size_max)
        if algorithm is not None:               # rung 0 keeps gmsh's default algo
            gmsh.option.setNumber("Mesh.Algorithm", algorithm)

        # None (and no change at all) unless the B-rep predicts a first pass
        # clearly over the analysis budget; see _PREDICT_OVER.
        flat = _flat_coarse_sizing(size_max, diag)
        first_pass = time.perf_counter()
        gmsh.model.mesh.generate(2)          # 2D surface mesh = triangulated shell
        fit = _fit_to_budget(               # no-op unless over the analysis budget
            size_max, started, time.perf_counter() - first_pass, flat)
        if fit is not None:
            logger.info("STEP mesh refit to the analysis budget: %s", fit)

        node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
        if node_coords.size == 0:
            raise ValueError("STEP file produced no meshable geometry.")
        verts = node_coords.reshape(-1, 3)
        tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}

        etypes, _etags, enodes = gmsh.model.mesh.getElements(dim=2)
        tris = []
        for et, conn in zip(etypes, enodes):
            if et == 2:                       # gmsh type 2 == 3-node triangle
                tris.append(np.fromiter((tag_to_idx[int(n)] for n in conn),
                                        dtype=np.int64).reshape(-1, 3))
        if not tris:
            raise ValueError("STEP file contains no surface triangles after tessellation.")
        faces = np.vstack(tris)
        try:
            data = _cad_face_data()
        except Exception:
            logger.warning("B-rep face data unavailable; using the mesh alone", exc_info=True)
            data = None
        if data is not None and len(data[CAD_FACES_KEY]) == len(faces):
            _LAST_CAD.update(data)
            if cad is not None:
                cad.update(data)
        return verts, faces
    finally:
        gmsh.finalize()


def prewarm_step_from_bytes(
    data: bytes, filename: str = "prewarm.step"
) -> trimesh.Trimesh:
    """Run one deliberately coarse real OCC import + surface mesh at boot.

    This pays gmsh/OCC's first-read and first-mesh initialization without using
    production tessellation density for a throwaway readiness fixture. Product
    parses still use ``_TARGET_DIAG_SEGMENTS`` through ``_run_rung`` unchanged.
    """
    if not _HAS_GMSH:
        raise RuntimeError("gmsh not installed")

    import tempfile

    suffix = Path(filename).suffix.lower() or ".step"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w+b")
    try:
        os.chmod(tmp.name, 0o600)
        tmp.write(data)
        tmp.flush()
        tmp.close()
        with _GMSH_LOCK:
            verts, faces = _tessellate_once(
                tmp.name,
                algorithm=None,
                curvature_pts=0.0,
                heal=False,
                target_diag_segments=1,
            )
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        mesh.metadata["source_format"] = "cad"  # ScaleCAD made these triangles
        return mesh
    finally:
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass


def _run_rung(path: str, idx: int) -> trimesh.Trimesh:
    """Execute a SINGLE ladder rung (by index) and return a processed
    ``trimesh.Trimesh``.

    Serialized on ``_GMSH_LOCK`` (the gmsh context is process-global). Raises
    ``_StepReadError`` if OCC cannot read the shape (caller aborts the ladder),
    ``_EmptyMeshError`` if the rung produced an empty mesh (caller advances), or
    any OTHER exception if the rung failed to mesh a readable shape (caller
    advances). This is the ONE place a rung runs — both the in-thread ladder
    (``_mesh_step_file``) and the per-rung subprocess orchestrator
    (``parse_pool``) call it, so rung logic/order stay identical across paths.

    Isolating ONE rung per call is what makes the per-rung wall-clock cap possible
    in ``parse_pool``: gmsh's ``mesh.generate`` is an uninterruptible in-thread C
    call, so a rung can only be time-bounded by running THIS function in a
    separately-timed, killable subprocess.
    """
    _name, algorithm, curvature_pts, heal = _MESH_RUNGS[idx]
    with _GMSH_LOCK:                         # serialize the global gmsh context
        _LAST_CAD.clear()
        verts, faces = _tessellate_once(path, algorithm, curvature_pts, heal)
        cad = dict(_LAST_CAD)
        _LAST_CAD.clear()
    # process=True merges coincident vertices -> recovers watertightness on single
    # solids whose faces share edges.
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise _EmptyMeshError("STEP tessellation yielded an empty mesh.")
    if cad and len(cad[CAD_FACES_KEY]) == len(mesh.faces):
        # Merging vertices keeps the faces in order (no validation pass drops any);
        # fix_normals below only flips windings, which a draft reading ignores.
        mesh.metadata.update(cad)
    if not mesh.is_winding_consistent:
        # gmsh emits triangles per B-rep surface patch, and patch windings can
        # disagree after the vertex merge — an artifact of OUR tessellation, not
        # of the user's solid. Unify it here like the sibling STEP paths do
        # (step_parser / ap242_tessellated_parser both fix_normals their output)
        # so the ERROR-severity INCONSISTENT_NORMALS check only ever fires on
        # geometry the user actually supplied with flipped faces.
        try:
            mesh.fix_normals(multibody=True)
        except Exception:
            logger.warning("fix_normals failed on gmsh shell; leaving winding as-is")
    # ScaleCAD tessellated this CAD file itself: advice about the file's own
    # triangles (an STL's) doesn't apply (base_analyzer.decimation_issue).
    mesh.metadata["source_format"] = "cad"
    return mesh


def mesh_single_rung_from_bytes(data: bytes, filename: str, idx: int) -> trimesh.Trimesh:
    """Worker entry: run ONE ladder rung (``idx``) on STEP bytes IN THIS PROCESS.

    Mirrors ``step_to_trimesh_from_bytes``' temp-file discipline (0o600, guaranteed
    unlink). Picklable/importable at module scope so ``parse_pool`` can dispatch it
    to a spawn subprocess and time/kill it per rung. Raises the same tagged
    exceptions as ``_run_rung`` (``_StepReadError`` -> abort; ``_EmptyMeshError`` /
    other -> advance), which the orchestrator maps exactly as the in-thread ladder.
    """
    if idx == 0:
        from src.parsers.ap242_tessellated_parser import (
            AP242TessellationError,
            is_ap242_tessellated,
            parse_ap242_tessellated,
        )

        if is_ap242_tessellated(data):
            try:
                return parse_ap242_tessellated(data)
            except AP242TessellationError as exc:
                raise _StepReadError(
                    "Could not read the embedded AP242 tessellated geometry."
                ) from exc

    if not _HAS_GMSH:
        raise RuntimeError("gmsh not installed")

    import tempfile
    suffix = Path(filename).suffix.lower() or ".step"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w+b")
    try:
        os.chmod(tmp.name, 0o600)
        tmp.write(data)
        tmp.flush()
        tmp.close()
        return _run_rung(tmp.name, idx)
    finally:
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass


def ladder_failure_error(last_msg: str) -> ValueError:
    """Build the SPECIFIC, honest error raised when EVERY ladder rung failed.

    The route maps this ``ValueError`` -> 400 with this detail (NOT the generic
    "Failed to parse mesh file"), so the client learns WHY the part could not be
    tessellated. Shared by the in-thread ladder and the subprocess orchestrator so
    both surface byte-for-byte the same honest message.
    """
    n = len(_MESH_RUNGS)
    if "periodic" in last_msg.lower():
        return ValueError(
            f"Could not tessellate this part: gmsh cannot mesh a periodic "
            f"surface in the geometry (all {n} mesh strategies failed)."
        )
    return ValueError(
        f"Could not tessellate this part: gmsh could not mesh the geometry "
        f"[{last_msg[:120]}] (all {n} mesh strategies failed)."
    )


def _mesh_step_file(path: str) -> trimesh.Trimesh:
    """In-thread retry ladder (unchanged output). The route runs this off the event
    loop; ``parse_pool`` uses the subprocess orchestrator instead so each rung is
    separately time-bounded. Both share ``_run_rung`` + ``ladder_failure_error``."""
    last_msg = ""
    best_open: trimesh.Trimesh | None = None
    for idx, (name, _algo, _curv, _heal) in enumerate(_MESH_RUNGS):
        try:
            mesh = _run_rung(path, idx)
        except _StepReadError as exc:
            # Unreadable STEP: retrying with another algorithm cannot help.
            raise ValueError(
                "Could not read STEP geometry (not a valid/supported STEP file)."
            ) from exc
        except _EmptyMeshError as exc:
            last_msg = str(exc)
            continue
        except Exception as exc:                # this rung failed to MESH the shape
            last_msg = str(exc)
            nxt = _MESH_RUNGS[idx + 1][0] if idx + 1 < len(_MESH_RUNGS) else None
            if nxt is not None:
                logger.info(
                    "step mesher rung '%s' failed (%s); retrying with rung '%s'",
                    name, last_msg[:120], nxt,
                )
            continue

        # Non-empty is not enough: a later rung can often close a shell that the
        # primary algorithm emitted with boundary/non-manifold edges. Preserve
        # the least-defective open shell so a genuinely open STEP still reaches
        # the downstream GEOMETRY_INVALID gate if no strategy can close it.
        if not mesh.is_watertight:
            best_open = _prefer_open_shell(best_open, mesh)
            last_msg = f"rung '{name}' produced a non-watertight shell"
            nxt = _MESH_RUNGS[idx + 1][0] if idx + 1 < len(_MESH_RUNGS) else None
            if nxt is not None:
                logger.info(
                    "step mesher rung '%s' produced an open shell (%d defective "
                    "edges); retrying with rung '%s'",
                    name, _shell_defect_count(mesh), nxt,
                )
            continue

        if idx > 0:
            logger.info(
                "step mesher recovered on retry rung '%s' (faces=%d, watertight=%s)",
                name, len(mesh.faces), mesh.is_watertight,
            )
        return mesh

    if best_open is not None:
        logger.info(
            "step mesher found no watertight strategy; returning least-defective "
            "open shell for the downstream geometry gate (faces=%d, defects=%d)",
            len(best_open.faces), _shell_defect_count(best_open),
        )
        return best_open

    # Every rung failed -> a SPECIFIC, honest error naming the cause.
    raise ladder_failure_error(last_msg)

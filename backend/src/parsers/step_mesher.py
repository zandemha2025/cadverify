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
from pathlib import Path

import numpy as np
import trimesh

logger = logging.getLogger("cadverify.step_mesher")

_HAS_GMSH = False
try:
    import gmsh  # noqa: F401
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


def is_step_supported() -> bool:
    """True iff the gmsh STEP path is importable."""
    return _HAS_GMSH


def step_to_trimesh_from_bytes(data: bytes, filename: str = "upload.step") -> trimesh.Trimesh:
    """Parse STEP bytes -> watertight-where-possible ``trimesh.Trimesh``.

    Mirrors ``step_parser``'s temp-file discipline (0o600, guaranteed unlink).
    Raises ``ValueError`` with a SAFE, static-ish message on any parse/mesh
    failure (the route maps ``ValueError`` -> 400). Never leaks gmsh internals
    to the caller.
    """
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


def _tessellate_once(path: str, algorithm, curvature_pts: float, heal: bool):
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
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)          # no stdout spew
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")  # normalize to mm
        if heal:
            for opt in _OCC_HEAL_OPTS:                        # heal BEFORE import
                gmsh.option.setNumber(opt, 1)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", curvature_pts)
        gmsh.model.add("part")
        try:
            gmsh.model.occ.importShapes(path)   # STEP/IGES/BREP via OCC
            gmsh.model.occ.synchronize()
        except Exception as exc:                # OCC reader rejected the file
            raise _StepReadError(str(exc)) from exc

        # scale-aware element budget: ~_TARGET_DIAG_SEGMENTS across the diagonal
        xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
        diag = ((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2) ** 0.5
        size_max = min(max(diag / _TARGET_DIAG_SEGMENTS, _MIN_SIZE_MM), _MAX_SIZE_MM)
        gmsh.option.setNumber("Mesh.MeshSizeMax", size_max)
        if algorithm is not None:               # rung 0 keeps gmsh's default algo
            gmsh.option.setNumber("Mesh.Algorithm", algorithm)

        gmsh.model.mesh.generate(2)          # 2D surface mesh = triangulated shell

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
        return verts, faces
    finally:
        gmsh.finalize()


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
        verts, faces = _tessellate_once(path, algorithm, curvature_pts, heal)
    # process=True merges coincident vertices -> recovers watertightness on single
    # solids whose faces share edges.
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise _EmptyMeshError("STEP tessellation yielded an empty mesh.")
    return mesh


def mesh_single_rung_from_bytes(data: bytes, filename: str, idx: int) -> trimesh.Trimesh:
    """Worker entry: run ONE ladder rung (``idx``) on STEP bytes IN THIS PROCESS.

    Mirrors ``step_to_trimesh_from_bytes``' temp-file discipline (0o600, guaranteed
    unlink). Picklable/importable at module scope so ``parse_pool`` can dispatch it
    to a spawn subprocess and time/kill it per rung. Raises the same tagged
    exceptions as ``_run_rung`` (``_StepReadError`` -> abort; ``_EmptyMeshError`` /
    other -> advance), which the orchestrator maps exactly as the in-thread ladder.
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

        if idx > 0:
            logger.info(
                "step mesher recovered on retry rung '%s' (faces=%d, watertight=%s)",
                name, len(mesh.faces), mesh.is_watertight,
            )
        return mesh

    # Every rung failed -> a SPECIFIC, honest error naming the cause.
    raise ladder_failure_error(last_msg)

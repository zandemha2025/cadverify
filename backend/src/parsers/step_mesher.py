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

import os
import threading
from pathlib import Path

import numpy as np
import trimesh

_HAS_GMSH = False
try:
    import gmsh  # noqa: F401
    _HAS_GMSH = True
except ImportError:
    pass

# gmsh is process-global / not thread-safe; serialize across worker threads.
_GMSH_LOCK = threading.Lock()

# Tessellation tuning (mm). Curvature-adaptive, with a face budget guard.
_CURVATURE_PTS = 12.0        # min facets around a full circle
_TARGET_DIAG_SEGMENTS = 200  # MeshSizeMax ~ bbox_diagonal / this
_MIN_SIZE_MM = 0.05          # floor so tiny parts still tessellate
_MAX_SIZE_MM = 50.0          # ceiling so huge parts don't vanish


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


def _mesh_step_file(path: str) -> trimesh.Trimesh:
    with _GMSH_LOCK:                         # serialize the global gmsh context
        # interruptible=False: skip gmsh's SIGINT handler install, which calls
        # signal.signal() and only works on the MAIN thread. The route meshes in
        # a ThreadPoolExecutor (A.5), so the default would raise "signal only
        # works in main thread of the main interpreter".
        gmsh.initialize(interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)          # no stdout spew
            gmsh.option.setString("Geometry.OCCTargetUnit", "MM")  # normalize to mm
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", _CURVATURE_PTS)
            gmsh.model.add("part")
            try:
                gmsh.model.occ.importShapes(path)   # STEP/IGES/BREP via OCC
                gmsh.model.occ.synchronize()
            except Exception as exc:                # OCC reader rejected the file
                raise ValueError(
                    "Could not read STEP geometry (not a valid/supported STEP file)."
                ) from exc

            # scale-aware element budget: ~_TARGET_DIAG_SEGMENTS across the diagonal
            xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
            diag = ((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2) ** 0.5
            size_max = min(max(diag / _TARGET_DIAG_SEGMENTS, _MIN_SIZE_MM), _MAX_SIZE_MM)
            gmsh.option.setNumber("Mesh.MeshSizeMax", size_max)

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
        finally:
            gmsh.finalize()

    # process=True merges coincident vertices -> recovers watertightness on
    # single solids whose faces share edges. Outside the gmsh lock (pure numpy).
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise ValueError("STEP tessellation yielded an empty mesh.")
    return mesh

"""Parse STEP files and convert to trimesh for analysis.

Uses cadquery/OCP (OpenCascade) for STEP parsing. Falls back to a
stub if cadquery is not installed (it requires OpenCascade C++ libs).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import numpy as np
import trimesh

_HAS_CADQUERY = False
try:
    import cadquery as cq
    _HAS_CADQUERY = True
except ImportError:
    pass

_HAS_OCP = False
try:
    from OCP.STEPControl import STEPControl_Reader  # noqa: F401
    from OCP.IFSelect import IFSelect_RetDone  # noqa: F401
    _HAS_OCP = True
except ImportError:
    pass


def is_step_supported() -> bool:
    """Check if STEP parsing is available."""
    return _HAS_CADQUERY or _HAS_OCP


def parse_step(file_path: str | Path, linear_deflection: float = 0.1) -> trimesh.Trimesh:
    """Load a STEP file and convert to a triangulated mesh.

    Args:
        file_path: Path to .step or .stp file.
        linear_deflection: Tessellation quality (smaller = finer mesh).

    Returns:
        A trimesh.Trimesh object ready for analysis.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"STEP file not found: {path}")
    if path.suffix.lower() not in (".step", ".stp"):
        raise ValueError(f"Expected .step/.stp file, got: {path.suffix}")

    if _HAS_CADQUERY:
        return _parse_with_cadquery(path, linear_deflection)

    raise RuntimeError(
        "STEP parsing requires cadquery. Install with: pip install cadquery"
    )


def _parse_with_cadquery(path: Path, linear_deflection: float) -> trimesh.Trimesh:
    """Parse STEP using cadquery and tessellate to trimesh."""
    result = cq.importers.importStep(str(path))

    # Tessellate to get vertices and triangles
    vertices_list = []
    faces_list = []
    vertex_offset = 0

    for shape in result.objects:
        tess = shape.tessellate(linear_deflection)
        verts = np.array([(v.x, v.y, v.z) for v in tess[0]])
        tris = np.array(tess[1]) + vertex_offset

        vertices_list.append(verts)
        faces_list.append(tris)
        vertex_offset += len(verts)

    if not vertices_list:
        raise ValueError(f"No geometry found in STEP file: {path}")

    all_vertices = np.vstack(vertices_list)
    all_faces = np.vstack(faces_list)

    mesh = trimesh.Trimesh(vertices=all_vertices, faces=all_faces)
    mesh.fix_normals()

    return mesh


def parse_step_from_bytes(
    data: bytes,
    filename: str = "upload.step",
    linear_deflection: float = 0.1,
) -> trimesh.Trimesh:
    """Parse STEP from raw bytes by writing to a temp file.

    STEP parsing typically requires file access (OpenCascade limitation).
    """
    import tempfile

    suffix = Path(filename).suffix or ".step"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w+b")
    try:
        os.chmod(tmp.name, 0o600)   # owner R/W only — CONCERNS.md security note
        tmp.write(data)
        tmp.flush()
        tmp.close()                  # close FD before cadquery re-opens by path
        return parse_step(tmp.name, linear_deflection)
    finally:
        # guaranteed cleanup even if parse_step raises
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass

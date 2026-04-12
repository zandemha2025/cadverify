"""Parse STL files into trimesh objects for analysis."""

from __future__ import annotations

from pathlib import Path

import trimesh


def parse_stl(file_path: str | Path) -> trimesh.Trimesh:
    """Load an STL file and return a trimesh object.

    Handles both binary and ASCII STL formats.
    Raises ValueError if the file cannot be parsed.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"STL file not found: {path}")
    if path.suffix.lower() != ".stl":
        raise ValueError(f"Expected .stl file, got: {path.suffix}")

    mesh = trimesh.load(str(path), file_type="stl", force="mesh")

    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"Failed to load as single mesh: {path}")

    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise ValueError(f"Empty mesh loaded from: {path}")

    return mesh


def parse_stl_from_bytes(data: bytes, filename: str = "upload.stl") -> trimesh.Trimesh:
    """Parse STL from raw bytes (for file upload handling)."""
    import io

    file_obj = io.BytesIO(data)
    mesh = trimesh.load(file_obj, file_type="stl", force="mesh")

    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"Failed to parse STL data from: {filename}")

    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise ValueError(f"Empty mesh from: {filename}")

    return mesh

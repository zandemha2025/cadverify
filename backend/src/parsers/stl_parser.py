"""Parse STL files into trimesh objects for analysis."""

from __future__ import annotations

from pathlib import Path
import struct

import numpy as np
import trimesh


def binary_stl_triangle_count(data: bytes) -> int | None:
    """Distinguish exact-length binary STL, including headers starting 'solid'."""
    if len(data) < 84:
        return None
    (count,) = struct.unpack_from("<I", data, 80)
    return count if 84 + count * 50 == len(data) else None


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

    return parse_stl_from_bytes(path.read_bytes(), str(path))


def parse_stl_from_bytes(data: bytes, filename: str = "upload.stl") -> trimesh.Trimesh:
    """Parse STL from raw bytes (for file upload handling)."""
    import io

    file_obj = io.BytesIO(data)
    mesh = trimesh.load(file_obj, file_type="stl", force="mesh")

    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"Failed to parse STL data from: {filename}")

    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise ValueError(f"Empty mesh from: {filename}")

    if binary_stl_triangle_count(data) is not None:
        # Half an IEEE float32 ULP per axis, including subnormals. Keep the
        # Euclidean vertex-error bound in mesh units through copies/transforms.
        magnitude = np.abs(mesh.vertices).max(axis=0)
        if not np.all(np.isfinite(magnitude)):
            raise ValueError(f"Non-finite STL coordinates from: {filename}")
        _, exponent = np.frexp(magnitude)
        spacing_exponent = np.where(magnitude == 0, -149, np.maximum(exponent - 24, -149))
        half_ulp = np.ldexp(np.ones(3), spacing_exponent - 1)
        mesh.metadata["coordinate_error"] = float(np.linalg.norm(half_ulp))
    return mesh

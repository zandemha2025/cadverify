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


# Window size for the ASCII facet count: the scan lowercases one window at a
# time, so its memory stays bounded however large the file is.
_ASCII_SCAN_CHUNK = 1 << 20
_VERTEX = b"vertex"


def ascii_stl_facet_count(data: bytes) -> int:
    """Facets trimesh's ASCII reader would build from ``data``.

    trimesh reads one vertex per ``vertex`` keyword (any letter case) and three
    vertices per facet, so this is that keyword count divided by three. The
    count runs over fixed-size windows instead of decoding the whole file.
    """
    step = max(1, int(_ASCII_SCAN_CHUNK))
    tail = len(_VERTEX) - 1
    total = 0
    for start in range(0, len(data), step):
        # The window runs ``tail`` bytes past its share, so a keyword that
        # starts in this share is seen whole and counted here exactly once.
        total += data[start:start + step + tail].lower().count(_VERTEX)
    return total // 3


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
    mesh.metadata["source_format"] = "stl"
    return mesh

"""Deterministic, DISTINCT heavy STEP part generator for parse benchmarks/tests.

The parse-concurrency measurement needs several DISTINCT parts so the in-process
mesh cache cannot short-circuit the second/third parse (distinct bytes => distinct
sha256 => distinct cache key). Rather than commit large binary STEP blobs, we
synthesize parts on demand from an integer index via gmsh's OCC kernel — fully
reproducible, byte-stable per (index, machine gmsh version).

Each part is a box of index-dependent dimensions with a spherical pocket cut out;
the curvature drives a ~180k-triangle tessellation (~seconds), matching the heavy
STEP parts the load smoke exercised. Distinct indices => distinct geometry =>
distinct bytes.
"""
from __future__ import annotations

import os
import tempfile


def generate_step_part(idx: int) -> bytes:
    """Return STEP bytes for a distinct, heavy single-solid part keyed by ``idx``.

    Reproducible: the same ``idx`` yields the same geometry. Different ``idx``
    yields different dimensions AND a different pocket radius, so the bytes (and
    thus the mesh-cache key) differ.
    """
    import gmsh

    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(f"part{idx}")
        length = 40.0 + float(idx)          # distinct extent per index
        width = 30.0
        height = 20.0
        box = gmsh.model.occ.addBox(0, 0, 0, length, width, height)
        radius = 8.0 + 0.5 * float(idx)     # distinct curvature per index
        sphere = gmsh.model.occ.addSphere(length / 2, width / 2, height / 2, radius)
        gmsh.model.occ.cut([(3, box)], [(3, sphere)])
        gmsh.model.occ.synchronize()
        fd, path = tempfile.mkstemp(suffix=".step")
        os.close(fd)
        gmsh.write(path)
    finally:
        gmsh.finalize()
    try:
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def generate_distinct_parts(count: int) -> list[bytes]:
    """Return ``count`` distinct heavy STEP parts (indices 0..count-1)."""
    return [generate_step_part(i) for i in range(count)]

"""The engine's nearest-surface queries are bounded in memory and answer exactly as trimesh.

``GeometryContext.maximum_inscribed_diameter`` asks how far interior points are
from the surface. trimesh's closest_point measures each point against every
triangle out to its nearest vertex, all at once; from inside a finely meshed
round pin that is the whole pin for every point (193 MB for one 8,288-sided pin
of a STEP assembly). ``context._closest_points_bounded`` calls the same query on
groups of points whose candidate triangles total at most
``_NEAREST_PAIRS_PER_CALL``, so each point's answer is trimesh's own.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import numpy as np
import pytest
import trimesh

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Stated bound (MB above the subprocess's baseline) for 48 interior points of an
# 8,288-sided cylinder, the batch the engine sends for a mesh that size.
# Measured: 77 MB; trimesh's closest_point at once took 446 MB.
_PIN_POINTS_BOUND_MB = 160


@pytest.mark.parametrize("budget", [10**12, 5000, 300, 1])
def test_grouped_queries_answer_exactly_as_trimesh(budget, monkeypatch):
    from src.analysis import context as cx

    monkeypatch.setattr(cx, "_NEAREST_PAIRS_PER_CALL", budget)
    rng = np.random.default_rng(5)
    for mesh in (trimesh.creation.icosphere(subdivisions=4, radius=10),
                 trimesh.creation.cylinder(radius=8, height=25, sections=2000),
                 trimesh.creation.annulus(r_min=3, r_max=6, height=40, sections=300),
                 trimesh.creation.box(extents=[50, 20, 5])):
        lo, hi = mesh.bounds
        # points around and inside it, on its faces, and on its vertices (where triangles tie)
        points = np.vstack([rng.uniform(lo - 2, hi + 2, size=(400, 3)), mesh.triangles_center[:100],
                            mesh.vertices[:40]])
        expected = mesh.nearest.on_surface(points)
        got = cx._closest_points_bounded(mesh, points)
        for a, b in zip(expected, got):
            np.testing.assert_array_equal(a, b)
            assert a.dtype == b.dtype


def test_interior_points_of_a_fine_pin_stay_bounded():
    if not os.path.exists("/proc/self/status"):
        pytest.skip("peak memory is read from /proc")
    script = textwrap.dedent(f"""
        import json, sys
        sys.path.insert(0, {BACKEND!r})
        import numpy as np, trimesh
        from src.analysis import context as cx

        def status(key):
            for line in open("/proc/self/status"):
                if line.startswith(key + ":"):
                    return int(line.split()[1]) // 1024
            return 0

        pin = trimesh.creation.cylinder(radius=8, height=25, sections=8288)
        pin.triangles_tree, pin.kdtree
        rng = np.random.default_rng(0)
        points = np.column_stack([rng.uniform(-2, 2, 48), rng.uniform(-2, 2, 48), rng.uniform(-3, 3, 48)])
        base = status("VmRSS")
        try:
            open("/proc/self/clear_refs", "w").write("5")
        except OSError:
            base = max(base, status("VmHWM"))
        _c, distance, _t = cx._closest_points_bounded(pin, points)
        print(json.dumps({{"added_mb": status("VmHWM") - base,
                           "nearest_mm": float(distance.min()), "farthest_mm": float(distance.max())}}))
    """)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=300)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    assert lines, proc.stdout[-2000:] + proc.stderr[-2000:]
    out = json.loads(lines[-1])
    assert out["added_mb"] < _PIN_POINTS_BOUND_MB, out
    # within 2.83 mm of the axis and at least 9.5 mm from the ends: 5.17-8 mm from the side
    assert 5.0 < out["nearest_mm"] <= out["farthest_mm"] <= 8.0

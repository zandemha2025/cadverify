"""Reading what a file holds stays bounded in memory and work, for any input.

A 29 KB STEP file whose faces never sewed tessellates to about 150k open faces
in three bodies. ``part_types.contact_between`` measured each sample point
against the other body with trimesh's closest_point, which takes every triangle
out to the point's nearest vertex at once: on big open sheets that is most of
the sheet for every point, and the worker grew without bound (6.1 GB when
stopped). A finely tessellated round pin did the same in ``stock_of`` (trimesh's
oriented box: 1.4 GB for one 8,288-sided pin). Now distances are computed in
batches, only as far as a contact can be, under a work cap per pair and per
file; the oriented box past a size is measured by rotating calipers. Normal
parts read exactly as before, and work the caps leave undone is said.

The memory bounds are measured in a fresh subprocess (peak resident set above
its own baseline), one at a time.
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

from tests import part_type_cases as cases

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Stated bounds (MB above the subprocess's baseline). Measured: 44 MB for the
# sheet (the old code passed 2.5 GB in 18 s and kept growing), 3 MB for the pin.
_SHEET_BOUND_MB = 250
_PIN_BOUND_MB = 100

_PRELUDE = """
import json, os, sys, threading, time
sys.path.insert(0, {backend!r})
import numpy as np, trimesh
from src.analysis import part_types as pt

def status(key):
    for line in open("/proc/self/status"):
        if line.startswith(key + ":"):
            return int(line.split()[1]) // 1024
    return 0

def measure(fn):
    base = status("VmRSS")
    try:
        open("/proc/self/clear_refs", "w").write("5")  # the peak starts again from here
    except OSError:
        base = max(base, status("VmHWM"))
    def guard():  # a regression must not take the machine down with it
        while True:
            if status("VmRSS") - base > 1500:
                print(json.dumps({{"killed_above_mb": status("VmRSS") - base}}), flush=True)
                os._exit(3)
            time.sleep(0.05)
    threading.Thread(target=guard, daemon=True).start()
    out = fn()
    return status("VmHWM") - base, out
"""


def _run(body: str) -> dict:
    if not os.path.exists("/proc/self/status"):
        pytest.skip("peak memory is read from /proc")
    script = _PRELUDE.format(backend=BACKEND) + textwrap.dedent(body)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=300)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    assert lines, proc.stdout[-2000:] + proc.stderr[-2000:]
    out = json.loads(lines[-1])
    assert "killed_above_mb" not in out, f"memory ran away: {out}"
    return out


# ── bounded memory ──────────────────────────────────────────────────────────


def test_a_contact_between_big_open_sheets_stays_bounded():
    """An open tray of about 147k faces and a sheet slanting through it from corner to corner.

    Every point on the sheet is far from the tray's vertices, so trimesh's search
    box held most of the tray for each point.
    """
    out = _run("""
        def grid(origin, u, v, nu, nv):
            i, j = np.meshgrid(np.arange(nu + 1), np.arange(nv + 1), indexing="ij")
            verts = (np.asarray(origin, float) + i[..., None] * (np.asarray(u, float) / nu)
                     + j[..., None] * (np.asarray(v, float) / nv)).reshape(-1, 3)
            idx = i * (nv + 1) + j
            a, b, c, d = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
            faces = np.concatenate([np.column_stack([a, b, c]), np.column_stack([a, c, d])])
            return trimesh.Trimesh(verts, faces, process=False)

        L, W, H, h = 100.0, 60.0, 30.0, 0.46
        nl, nw, nh = round(L / h), round(W / h), round(H / h)
        tray = trimesh.util.concatenate([
            grid([0, 0, 0], [L, 0, 0], [0, W, 0], nl, nw),
            grid([0, 0, 0], [L, 0, 0], [0, 0, H], nl, nh), grid([0, W, 0], [L, 0, 0], [0, 0, H], nl, nh),
            grid([0, 0, 0], [0, W, 0], [0, 0, H], nw, nh), grid([L, 0, 0], [0, W, 0], [0, 0, H], nw, nh)])
        tray.merge_vertices()
        sheet = trimesh.Trimesh([[0, 0, 0], [0, W, 0], [L, W, H], [L, 0, H]], [[0, 1, 2], [0, 2, 3]], process=False)
        bodies, _info = pt.split_bodies(trimesh.util.concatenate([tray, sheet]))
        added, contact = measure(lambda: pt.contact_between(bodies[0], bodies[1], seed=1))
        print(json.dumps({"faces": [len(b.faces) for b in bodies], "closed": [b.closed for b in bodies],
                          "added_mb": added, "contact": contact}))
    """)
    assert out["faces"][0] > 140_000 and out["closed"] == [False, False]
    assert out["added_mb"] < _SHEET_BOUND_MB, out
    # the sheet's edges lie on the tray's walls and floor: it touches, and is measured in full
    assert out["contact"]["type"] == "touching" and "coarse" not in out["contact"]


def test_a_finely_tessellated_round_bar_reads_in_bounded_memory():
    out = _run("""
        rod = trimesh.creation.cylinder(radius=10, height=300, sections=8288)
        rod.convex_hull
        added, stock = measure(lambda: pt.stock_of(rod, rod.volume))
        print(json.dumps({"added_mb": added, "stock": stock}, default=float))
    """)
    assert out["added_mb"] < _PIN_BOUND_MB, out
    assert out["stock"]["kind"] == "round_bar" and out["stock"]["od_mm"] == pytest.approx(20, abs=0.05)
    assert out["stock"]["words"] == "Round bar Ø20 mm, 300 mm long"


# ── the same answers ────────────────────────────────────────────────────────


def _mesh(data: bytes, name: str = "part.stl"):
    from src.api.routes import _parse_mesh

    mesh, _suffix = _parse_mesh(data, name)
    return mesh


def _overlapping_cubes() -> bytes:
    return cases.stl(cases.box([0, 0, 0], [30, 30, 30]), cases.box([20, 5, 5], [50, 25, 25]))


def _cube_row(n: int = 12) -> bytes:
    """A row of cubes, each touching the next (staggered, so their faces share no edges)."""
    return cases.stl(*[cases.box([10 * i, 3 * (i % 2), 0], [10 * i + 10, 3 * (i % 2) + 10, 10]) for i in range(n)])


def _without_timing(out: dict) -> dict:
    out = dict(out)
    out.pop("elapsed_sec", None)
    return out


def test_distances_in_batches_equal_trimesh_closest_point(monkeypatch):
    from src.analysis import part_types as pt

    mesh = trimesh.creation.icosphere(subdivisions=3, radius=20)
    rng = np.random.default_rng(7)
    points = rng.normal(size=(600, 3))
    points = points / np.linalg.norm(points, axis=1, keepdims=True) * rng.uniform(5, 30, size=(600, 1))
    _c, ref, _t = trimesh.proximity.closest_point(mesh, points)
    surface = pt._NearSurface(mesh, np.arange(len(mesh.faces)))
    reach = surface.vertex_reach(points)
    full, used, done = surface.nearest(points, reach, budget=10**9)
    assert done == len(points) and used > 0
    np.testing.assert_allclose(full, ref, rtol=0, atol=1e-9)
    # looking only as far as a contact can be: exact within it, inf beyond
    near_reach = pt.NEAR_TOL_MM + trimesh.tol.merge
    near, _used, _done = surface.nearest(points, np.minimum(reach, near_reach), budget=10**9)
    within = ref <= pt.NEAR_TOL_MM
    np.testing.assert_allclose(near[within], ref[within], rtol=0, atol=1e-9)
    assert np.all(np.isinf(near[ref > near_reach]))
    # far points measured by growing their reach: exact too
    far = ref > near_reach
    deep, _used, whole = surface.exact(points[far], near_reach, budget=10**9)
    assert whole
    np.testing.assert_allclose(deep, ref[far], rtol=0, atol=1e-9)
    # one point at a time, seven distances per batch: the same numbers
    monkeypatch.setattr(pt, "_CONTACT_CHUNK_POINTS", 1)
    monkeypatch.setattr(pt, "_CONTACT_BATCH", 7)
    small, _used, _done = surface.nearest(points, reach, budget=10**9)
    np.testing.assert_array_equal(small, full)
    # a budget stops between chunks and says how far it got
    cut, used, done = surface.nearest(points, reach, budget=500)
    assert used <= 500 and 0 < done < len(points)
    np.testing.assert_array_equal(cut[:done], full[:done])
    assert np.all(np.isinf(cut[done:]))


class _Unbounded:
    """The old measurement: trimesh's closest_point on every point at once."""

    def __init__(self, mesh, faces):
        tri = np.asarray(mesh.triangles, dtype=np.float64)[np.asarray(faces, dtype=np.int64)]
        self.mesh = trimesh.Trimesh(tri.reshape(-1, 3), np.arange(len(tri) * 3).reshape(-1, 3), process=False)

    def vertex_reach(self, points):
        return np.full(len(points), np.inf)

    def nearest(self, points, radius, budget):
        _c, d, _t = trimesh.proximity.closest_point(self.mesh, points)
        return np.where(d <= radius, d, np.inf), 0, len(points)

    def exact(self, points, beyond, budget):
        _c, d, _t = trimesh.proximity.closest_point(self.mesh, points)
        return np.asarray(d, dtype=np.float64), 0, True


@pytest.mark.parametrize("make", [cases.cube_with_fixture, cases.welded_frame, cases.t_joint,
                                  cases.l_bracket_welded, _overlapping_cubes])
def test_bounded_contacts_equal_unbounded_ones_on_small_parts(make, monkeypatch):
    from src.analysis import part_types as pt

    mesh = _mesh(make())
    bounded = _without_timing(pt.describe(mesh.copy()))
    assert bounded["contacts"] and bounded["contacts_complete"] is True
    assert all("coarse" not in c for c in bounded["contacts"])
    with monkeypatch.context() as m:
        m.setattr(pt, "_NearSurface", _Unbounded)
        assert _without_timing(pt.describe(mesh.copy())) == bounded
    with monkeypatch.context() as m:  # chunked to the extreme
        m.setattr(pt, "_CONTACT_CHUNK_POINTS", 1)
        m.setattr(pt, "_CONTACT_BATCH", 5)
        assert _without_timing(pt.describe(mesh.copy())) == bounded
    if make is _overlapping_cubes:
        (contact,) = bounded["contacts"]
        assert contact["type"] == "overlap" and contact["overlap_mm"] > 5


def test_a_bounded_oriented_box_matches_trimesh(monkeypatch):
    from src.analysis import part_types as pt

    rng = np.random.default_rng(3)
    for _ in range(40):
        pts = rng.normal(size=(int(rng.integers(3, 600)), 2)) * rng.uniform(0.1, 50, size=2)
        _t, rect = trimesh.bounds.oriented_bounds_2D(pts)
        area, d = pt._min_rectangle(pts)
        assert area == pytest.approx(float(np.prod(rect)), rel=1e-9)
        across = np.array([-d[1], d[0]])
        assert np.ptp(pts @ d) * np.ptp(pts @ across) == pytest.approx(area, rel=1e-9)
    pipe = trimesh.creation.annulus(r_min=21, r_max=24, height=500, sections=64)
    before = pt.stock_of(pipe, pipe.volume)
    to_origin, extents = pt._oriented_box(pipe)  # small hull: trimesh's own answer
    ref_origin, ref_extents = trimesh.bounds.oriented_bounds(pipe)
    np.testing.assert_array_equal(extents, ref_extents)
    np.testing.assert_array_equal(to_origin, ref_origin)
    monkeypatch.setattr(pt, "_OBB_MAX_CELLS", 0)  # every hull takes the bounded path
    _o, bounded = pt._oriented_box(pipe)
    np.testing.assert_allclose(bounded, ref_extents, rtol=1e-9)
    assert pt.stock_of(pipe, pipe.volume) == before


# ── what the caps leave undone is said ──────────────────────────────────────


def test_a_file_of_many_bodies_says_which_contacts_werent_checked(monkeypatch):
    from src.analysis import part_types as pt

    monkeypatch.setattr(pt, "_MAX_CONTACT_PAIRS", 4)
    out = pt.describe(_mesh(_cube_row(12)))
    assert out["body_count"] == 12 and out["kind"] == "assembly"
    assert len(out["contacts"]) == 4 and out["contacts_complete"] is False
    assert out["contacts_unchecked"] == {"pairs": 7, "of": 11, "reasons": ["pairs"]}
    assert out["contacts_note"] == ("Contacts weren't checked between 7 of the 11 pairs of bodies "
                                    "that sit close (only the first 4 pairs are measured).")
    assert out["summary"].endswith(out["contacts_note"])
    json.dumps(out)


def test_contacts_past_the_files_work_cap_are_said_not_guessed(monkeypatch):
    from src.analysis import part_types as pt

    monkeypatch.setattr(pt, "_CONTACT_WORK_PER_FILE", 1)
    out = pt.describe(_mesh(cases.welded_frame()))
    assert out["kind"] == "bodies" and out["contacts"] == [] and out["contacts_complete"] is False
    assert out["contacts_unchecked"] == {"pairs": 4, "of": 4, "reasons": ["work"]}
    assert out["summary"] == ("This file holds 4 separate bodies (4 tubes); whether they touch wasn't "
                              "measured (too much surface to measure within this check's limits).")


def test_a_contact_past_the_pairs_work_cap_is_marked_coarse():
    from src.analysis import part_types as pt

    bodies, _info = pt.split_bodies(_mesh(cases.cube_with_fixture()))
    whole, used, complete = pt._contact(bodies[0], bodies[1], seed=1, budget=10**9)
    assert complete and "coarse" not in whole
    part = pt.contact_between(bodies[0], bodies[1], seed=1, budget=used // 3)
    assert part["type"] == "touching" and part["coarse"] is True
    # a smaller random sample of the same seat: the area is an estimate of the same size
    assert part["area_mm2"] == pytest.approx(whole["area_mm2"], rel=0.5)

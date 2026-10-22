"""What a CAD file holds: one solid, or several bodies, and what kind of set they are.

ScaleCAD checks a file as one part. A weldment (plates and tubes welded together),
a part exported with its fixture, or several parts saved in one file are not one
part, and pricing them as one block gives a wrong answer. This module reads the
file's mesh (the same analysis mesh every check uses, so face indices line up with
the 3D view) and says what it holds:

* ``single_solid``: one closed body.
* ``single_solid_with_voids``: one body whose sealed internal voids are skins of
  their own (a nested shell is a void, not a second body).
* ``separate_bodies``: several bodies that don't touch.
* ``weldment``: bodies that touch along narrow joints, mostly cut stock (plate,
  sheet, tube, bar, angle, channel): likely welded together.
* ``assembly``: bodies that touch but don't read as welded stock (a part and its
  fixture, a bolt in a plate), or a STEP product tree with named parts.

Everything here is measured from the mesh. Stock shapes come from the body's
oriented box and three cross-sections along its length; contacts from points
sampled on one body and their distance to the other. Weld lengths are an estimate
(the outline of each contact patch, as if welded all round) and are labelled so.

Bodies are split at the mesh's manifold edges only: two closed bodies that share
an edge where they touch (a common STL export of a weldment) are two bodies, each
closed on its own, not one open shell.
"""
from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

import numpy as np
import trimesh

logger = logging.getLogger("cadverify.part_types")

# Bodies we describe one by one. Past this (unmerged triangle soup, a scan of
# confetti) the file is reported as "many bodies" without per-body detail.
_DEFAULT_MAX_BODIES = 200
# Pairs of bodies whose contacts we measure (bbox-prefiltered first).
_MAX_CONTACT_PAIRS = 400
# Shells nested-tested against each other (containment is O(n^2) ray tests).
_MAX_NESTING_SHELLS = 64

TOUCH_TOL_MM = 0.05      # a point this close to the other body touches it
NEAR_TOL_MM = 0.5        # closer than this, a gap a weld bridges
_SAMPLE_POINTS = 3000    # points per sampling round on the contact region
_SAMPLE_ROUNDS = 3
_MIN_REGION_POINTS = 400

STOCK_KINDS = frozenset({
    "plate", "sheet", "rect_tube", "round_tube", "round_bar", "flat_bar", "bar",
    "angle", "channel", "tee", "beam",
})
LONG_KINDS = frozenset({"rect_tube", "round_tube", "round_bar", "flat_bar", "bar", "angle", "channel", "tee", "beam"})
_PLURAL = {
    "plate": ("plate", "plates"), "sheet": ("sheet", "sheets"),
    "rect_tube": ("tube", "tubes"), "round_tube": ("round tube", "round tubes"),
    "round_bar": ("round bar", "round bars"), "flat_bar": ("flat bar", "flat bars"),
    "bar": ("bar", "bars"), "angle": ("angle", "angles"), "channel": ("channel", "channels"),
    "tee": ("tee", "tees"), "beam": ("beam", "beams"), "block": ("block", "blocks"),
    None: ("shaped part", "shaped parts"),
}


def max_bodies() -> int:
    try:
        value = int(os.getenv("PART_TYPE_MAX_BODIES", str(_DEFAULT_MAX_BODIES)))
    except ValueError:
        return _DEFAULT_MAX_BODIES
    return value if value > 0 else _DEFAULT_MAX_BODIES


# ---------------------------------------------------------------------------
# Shells and bodies
# ---------------------------------------------------------------------------


def shell_labels(mesh: trimesh.Trimesh) -> tuple[np.ndarray, int]:
    """Face -> shell label, joining faces only across edges exactly two faces share.

    ``mesh.face_adjacency`` already skips edges with three or more faces, so two
    closed bodies that share an edge where they touch come out as two shells.
    """
    n = len(mesh.faces)
    if n == 0:
        return np.zeros(0, dtype=np.int64), 0
    adjacency = np.asarray(mesh.face_adjacency, dtype=np.int64)
    if adjacency.size == 0:
        return np.arange(n, dtype=np.int64), n
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    graph = csr_matrix((np.ones(len(adjacency)), (adjacency[:, 0], adjacency[:, 1])), shape=(n, n))
    count, labels = connected_components(graph, directed=False)
    return np.asarray(labels, dtype=np.int64), int(count)


def _closed(faces: np.ndarray) -> bool:
    """Every edge of these triangles is used exactly twice among them."""
    if len(faces) < 4:
        return False
    edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return bool(np.all(counts == 2))


def _signed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    tri = vertices[faces]
    return float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0)


def _ranges(indices: np.ndarray) -> list[list[int]]:
    """Sorted face indices as half-open ``[start, end)`` runs (compact for the viewer)."""
    if len(indices) == 0:
        return []
    idx = np.sort(np.asarray(indices, dtype=np.int64))
    breaks = np.nonzero(np.diff(idx) != 1)[0]
    starts = np.concatenate([[idx[0]], idx[breaks + 1]])
    ends = np.concatenate([idx[breaks] + 1, [idx[-1] + 1]])
    return [[int(s), int(e)] for s, e in zip(starts, ends)]


@dataclass
class Shell:
    faces: np.ndarray            # face indices into the file mesh
    closed: bool
    volume: float                # signed, mm^3 (0 when open)
    lo: np.ndarray
    hi: np.ndarray
    depth: int = 0


@dataclass
class Body:
    index: int
    shells: list[Shell]
    faces: np.ndarray
    closed: bool
    volume: float
    area: float
    lo: np.ndarray
    hi: np.ndarray
    centroid: np.ndarray
    voids: int
    mesh: Optional[trimesh.Trimesh] = None
    stock: Optional[dict] = None
    design: int = 0
    name: Optional[str] = None
    extra: dict = field(default_factory=dict)
    # Same-design identity when the caller knows better than the mesh (a STEP
    # product's name, B-rep volume and face count), else measured.
    key: Optional[tuple] = None
    # The body's faces in the file's analysis mesh, when ``faces`` index another
    # mesh (a STEP product tree's own per-part meshes).
    view_faces: Optional[np.ndarray] = None


def _submesh(mesh: trimesh.Trimesh, faces: np.ndarray) -> trimesh.Trimesh:
    sub = mesh.submesh([np.asarray(faces, dtype=np.int64)], append=True, repair=False)
    if isinstance(sub, list):  # older trimesh
        sub = sub[0]
    return sub


def _probes(mesh: trimesh.Trimesh, faces: np.ndarray, k: int = 7) -> np.ndarray:
    """Centroids of k faces spread over a shell (a single vertex can sit on another skin)."""
    pick = faces[np.linspace(0, len(faces) - 1, num=min(k, len(faces))).astype(np.int64)]
    return mesh.triangles_center[pick]


def _nest(mesh: trimesh.Trimesh, shells: list[Shell]) -> None:
    """Set each shell's depth: how many other closed shells enclose it.

    A shell is enclosed by another only if its box sits inside the other's box and
    most of its probe points are inside the other; touching bodies (whose probes
    can land on the other's skin) fail the box test, so they stay separate.
    """
    closed = [s for s in shells if s.closed]
    if len(closed) < 2 or len(closed) > _MAX_NESTING_SHELLS:
        return
    order = sorted(closed, key=lambda s: -abs(s.volume))
    subs: dict[int, trimesh.Trimesh] = {}
    for i, inner in enumerate(order):
        probes = None
        for outer in order[:i]:
            span = np.maximum(outer.hi - outer.lo, 1e-9)
            tol = 1e-6 * float(np.max(span))
            if np.any(inner.lo < outer.lo - tol) or np.any(inner.hi > outer.hi + tol):
                continue
            if np.allclose(inner.lo, outer.lo, atol=tol) and np.allclose(inner.hi, outer.hi, atol=tol):
                continue
            if probes is None:
                probes = _probes(mesh, inner.faces)
            key = id(outer)
            if key not in subs:
                subs[key] = _submesh(mesh, outer.faces)
            try:
                inside = subs[key].contains(probes)
            except Exception:
                logger.warning("shell containment test failed", exc_info=True)
                continue
            if int(np.sum(inside)) * 2 > len(probes):
                inner.depth += 1


def split_bodies(mesh: trimesh.Trimesh, *, with_meshes: bool = True) -> tuple[list[Body], dict]:
    """The file's bodies, each with its sealed voids. Returns (bodies, info)."""
    labels, count = shell_labels(mesh)
    info: dict[str, Any] = {"shells": count}
    if count == 0:
        return [], info
    cap = max_bodies()
    if count > cap * 4:
        info["too_many_shells"] = True
        return [], info
    faces_all = np.asarray(mesh.faces, dtype=np.int64)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    order = np.argsort(labels, kind="stable")
    bounds = np.cumsum(np.bincount(labels, minlength=count))
    starts = np.concatenate([[0], bounds[:-1]])
    shells: list[Shell] = []
    for k in range(count):
        idx = order[starts[k]:bounds[k]]
        tri = faces_all[idx]
        closed = _closed(tri)
        pts = verts[np.unique(tri)]
        shells.append(Shell(
            faces=idx, closed=closed,
            volume=_signed_volume(verts, tri) if closed else 0.0,
            lo=pts.min(axis=0), hi=pts.max(axis=0),
        ))
    _nest(mesh, shells)
    outers = [s for s in shells if s.depth % 2 == 0]
    voids = [s for s in shells if s.depth % 2 == 1]
    groups: dict[int, list[Shell]] = {id(s): [s] for s in outers}
    for v in voids:
        # the smallest enclosing outer skin one level up
        host = None
        for o in sorted(outers, key=lambda s: abs(s.volume)):
            if o.depth == v.depth - 1 and np.all(v.lo >= o.lo - 1e-9) and np.all(v.hi <= o.hi + 1e-9):
                host = o
                break
        if host is None:
            groups[id(v)] = [v]
        else:
            groups[id(host)].append(v)
    if len(groups) > cap:
        info["too_many_bodies"] = len(groups)
        return [], info
    area_faces = mesh.area_faces
    bodies: list[Body] = []
    for members in groups.values():
        faces = np.concatenate([m.faces for m in members])
        outer = members[0]
        vol = abs(outer.volume) - sum(abs(m.volume) for m in members[1:])
        closed = all(m.closed for m in members)
        tri_c = mesh.triangles_center[faces]
        w = area_faces[faces]
        centroid = (tri_c * w[:, None]).sum(axis=0) / max(float(w.sum()), 1e-12)
        bodies.append(Body(
            index=0, shells=members, faces=np.sort(faces), closed=closed,
            volume=float(vol) if closed else 0.0, area=float(w.sum()),
            lo=outer.lo, hi=outer.hi, centroid=centroid, voids=len(members) - 1,
        ))
    # Largest first, then by position, so the same file always numbers its bodies the same.
    bodies.sort(key=lambda b: (-round(b.volume if b.closed else b.area, 3), *np.round(b.centroid, 3)))
    for i, b in enumerate(bodies, start=1):
        b.index = i
        if with_meshes:
            b.mesh = _submesh(mesh, b.faces)
    return bodies, info


def bodies_from_parts(
    parts: list[tuple[trimesh.Trimesh, Optional[str], Optional[tuple], dict]],
    view_mesh: Optional[trimesh.Trimesh] = None,
) -> tuple[Optional[trimesh.Trimesh], list[Body]]:
    """Bodies from a product tree's own per-part meshes (one solid each).

    ``parts``: (mesh in file coordinates, product name, design key, extra fields).
    When ``view_mesh`` (the file's analysis mesh) is given, each body also gets the
    faces of that mesh nearest to it, so the 3D view can light the body up.
    Returns the parts' combined mesh (the face space of ``Body.faces``) and bodies.
    """
    meshes = [p[0] for p in parts if p[0] is not None and len(p[0].faces)]
    if len(meshes) < 2:
        return None, []
    joined = trimesh.util.concatenate(meshes)
    if not isinstance(joined, trimesh.Trimesh):
        return None, []
    combined: trimesh.Trimesh = joined
    verts = np.asarray(combined.vertices, dtype=np.float64)
    faces_all = np.asarray(combined.faces, dtype=np.int64)
    bodies: list[Body] = []
    vert_owner = np.zeros(len(verts), dtype=np.int64)
    offset = 0
    voffset = 0
    kept = [p for p in parts if p[0] is not None and len(p[0].faces)]
    for k, (m, name, key, extra) in enumerate(kept):
        n = len(m.faces)
        idx = np.arange(offset, offset + n, dtype=np.int64)
        tri = faces_all[idx]
        vert_owner[voffset:voffset + len(m.vertices)] = k
        closed = _closed(tri)
        vol = abs(_signed_volume(verts, tri)) if closed else 0.0
        pts = verts[np.unique(tri)]
        w = combined.area_faces[idx]
        centroid = (combined.triangles_center[idx] * w[:, None]).sum(axis=0) / max(float(w.sum()), 1e-12)
        shell = Shell(faces=idx, closed=closed, volume=vol, lo=pts.min(axis=0), hi=pts.max(axis=0))
        bodies.append(Body(index=0, shells=[shell], faces=idx, closed=closed, volume=vol, area=float(w.sum()),
                           lo=shell.lo, hi=shell.hi, centroid=centroid, voids=0, mesh=m, name=name,
                           extra=dict(extra or {}), key=key))
        offset += n
        voffset += len(m.vertices)
    if view_mesh is not None and len(view_mesh.faces):
        try:
            from scipy.spatial import cKDTree  # pyright: ignore[reportAttributeAccessIssue]

            _d, nearest = cKDTree(verts).query(view_mesh.triangles_center, k=1)
            owner = vert_owner[np.asarray(nearest, dtype=np.int64)]
            for k, b in enumerate(bodies):
                b.view_faces = np.nonzero(owner == k)[0]
        except Exception:
            logger.warning("mapping product-tree bodies onto the analysis mesh failed", exc_info=True)
    bodies.sort(key=lambda b: (-round(b.volume if b.closed else b.area, 3), *np.round(b.centroid, 3)))
    for i, b in enumerate(bodies, start=1):
        b.index = i
    return combined, bodies


# ---------------------------------------------------------------------------
# Stock shape of one body
# ---------------------------------------------------------------------------


def _fmt(x: float) -> str:
    if x >= 100:
        return f"{x:.0f}"
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


def _section(mesh: trimesh.Trimesh, origin: np.ndarray, normal: np.ndarray):
    try:
        sec = mesh.section(plane_origin=origin, plane_normal=normal)
        if sec is None:
            return []
        planar, _ = sec.to_planar()
        return list(planar.polygons_full)
    except Exception:
        return []


def _reflex_and_pockets(poly) -> tuple[int, int]:
    """Concave corners of a simplified outline, and the pockets its convex hull adds."""
    tol = max(0.02 * math.sqrt(max(poly.area, 1e-9)), 0.05)
    simple = poly.simplify(tol, preserve_topology=True)
    ring = np.asarray(simple.exterior.coords)[:-1]
    if len(ring) < 3:
        return 0, 0
    if simple.exterior.is_ccw is False:
        ring = ring[::-1]
    prev = np.roll(ring, 1, axis=0)
    nxt = np.roll(ring, -1, axis=0)
    cross = (ring[:, 0] - prev[:, 0]) * (nxt[:, 1] - ring[:, 1]) - (ring[:, 1] - prev[:, 1]) * (nxt[:, 0] - ring[:, 0])
    reflex = int(np.sum(cross < -1e-9))
    pockets_geom = simple.convex_hull.difference(simple)
    big = [g for g in getattr(pockets_geom, "geoms", [pockets_geom]) if g.area > 0.02 * simple.area]
    return reflex, len(big)


def _rect_dims(poly) -> tuple[float, float]:
    rect = poly.minimum_rotated_rectangle
    xy = np.asarray(rect.exterior.coords)[:4]
    a = float(np.linalg.norm(xy[1] - xy[0]))
    b = float(np.linalg.norm(xy[2] - xy[1]))
    return (max(a, b), min(a, b))


def stock_of(body_mesh: trimesh.Trimesh, volume: float) -> Optional[dict]:
    """Read a body as cut stock: plate, sheet, tube, bar, angle, channel, tee, beam or block.

    None when it doesn't read as stock (a machined or moulded shape). Measured from
    the body's oriented box and three sections along its longest side.
    """
    if volume <= 0 or len(body_mesh.faces) < 4:
        return None
    try:
        to_origin, extents = trimesh.bounds.oriented_bounds(body_mesh)
    except Exception:
        return None
    extents = np.asarray(extents, dtype=np.float64)
    order = np.argsort(extents)
    t, w, length = (float(extents[i]) for i in order)
    if t <= 0:
        return None
    rot = np.asarray(to_origin[:3, :3])
    axes = rot[order]  # rows: unit axes in file coordinates, thinnest to longest
    center = trimesh.transform_points(np.zeros((1, 3)), np.linalg.inv(to_origin))[0]
    box = t * w * length
    fill = volume / box if box > 0 else 0.0
    out: dict[str, Any] = {"box_mm": [round(length, 2), round(w, 2), round(t, 2)], "fill": round(fill, 3)}

    def sect(axis_row: np.ndarray, frac: float, span: float):
        return _section(body_mesh, center + (frac - 0.5) * span * axis_row, axis_row)

    long_axis = axes[2]
    if length >= 2.5 * w:
        polys = [sect(long_axis, f, length) for f in (0.25, 0.5, 0.75)]
        areas = [sum(p.area for p in ps) for ps in polys]
        mid = polys[1]
        prismatic = (
            all(a > 0 for a in areas)
            and max(areas) <= 1.03 * min(areas)
            and 0.7 <= volume / (areas[1] * length) <= 1.03
        )
        if prismatic and len(mid) == 1:
            poly = mid[0]
            area = float(poly.area)
            outer = type(poly)(poly.exterior)
            perim_outer = float(outer.length)
            iso = 4 * math.pi * float(outer.area) / (perim_outer ** 2) if perim_outer > 0 else 0.0
            holes = len(poly.interiors)
            wall = 2 * area / float(poly.length) if poly.length > 0 else 0.0
            ends = "square" if volume >= 0.97 * area * length else "shaped"
            out.update({"length_mm": round(length, 1), "section_area_mm2": round(area, 1), "ends": ends})
            if holes == 1:
                if iso >= 0.95:
                    od = 2 * math.sqrt(float(outer.area) / math.pi)
                    out.update(kind="round_tube", od_mm=round(od, 2), wall_mm=round(wall, 2),
                               words=f"Round tube Ø{_fmt(od)} × {_fmt(wall)} mm, {_fmt(length)} mm long")
                else:
                    a, b = _rect_dims(outer)
                    name = "Square tube" if abs(a - b) <= 0.02 * a else "Rectangular tube"
                    out.update(kind="rect_tube", section_mm=[round(a, 2), round(b, 2)], wall_mm=round(wall, 2),
                               words=f"{name} {_fmt(a)} × {_fmt(b)} × {_fmt(wall)} mm, {_fmt(length)} mm long")
                out["thickness_mm"] = out["wall_mm"]
                return out
            if holes == 0:
                a, b = _rect_dims(poly)
                sec_fill = area / (a * b) if a * b > 0 else 0.0
                if iso >= 0.95:
                    d = 2 * math.sqrt(area / math.pi)
                    out.update(kind="round_bar", od_mm=round(d, 2), thickness_mm=round(d, 2),
                               words=f"Round bar Ø{_fmt(d)} mm, {_fmt(length)} mm long")
                    return out
                if sec_fill >= 0.95:
                    if b <= 0.5 * a:
                        out.update(kind="flat_bar", section_mm=[round(a, 2), round(b, 2)], thickness_mm=round(b, 2),
                                   words=f"Flat bar {_fmt(a)} × {_fmt(b)} mm, {_fmt(length)} mm long")
                    else:
                        name = "Square bar" if abs(a - b) <= 0.02 * a else "Bar"
                        out.update(kind="bar", section_mm=[round(a, 2), round(b, 2)], thickness_mm=round(b, 2),
                                   words=f"{name} {_fmt(a)} × {_fmt(b)} mm, {_fmt(length)} mm long")
                    return out
                if sec_fill <= 0.7 and 0 < wall <= 0.3 * b:
                    reflex, pockets = _reflex_and_pockets(poly)
                    kind, name = None, ""
                    if reflex == 1 and pockets == 1:
                        kind, name = "angle", "Angle"
                    elif reflex == 2 and pockets == 1:
                        kind, name = "channel", "Channel"
                    elif reflex == 2 and pockets == 2:
                        kind, name = "tee", "Tee"
                    elif reflex == 4 and pockets == 2:
                        kind, name = "beam", "Beam"
                    if kind == "angle":
                        # an L of legs a and b and thickness t has area t(a + b) - t^2
                        disc = (a + b) ** 2 - 4 * area
                        if disc >= 0:
                            wall = ((a + b) - math.sqrt(disc)) / 2
                    if kind:
                        out.update(kind=kind, section_mm=[round(a, 2), round(b, 2)], thickness_mm=round(wall, 2),
                                   words=f"{name} {_fmt(a)} × {_fmt(b)} × {_fmt(wall)} mm, {_fmt(length)} mm long")
                        return out
    if t <= 0.2 * w:
        # uniform thickness: the mid-thickness section times the thickness is the volume
        mid = _section(body_mesh, center, axes[0])
        flat = sum(p.area for p in mid)
        if flat > 0 and 0.9 <= volume / (flat * t) <= 1.05:
            kind = "sheet" if t < 6.0 else "plate"
            name = "Sheet" if kind == "sheet" else "Plate"
            out.update(kind=kind, thickness_mm=round(t, 2), outline_mm=[round(length, 1), round(w, 1)],
                       words=f"{name} {_fmt(t)} mm thick, {_fmt(length)} × {_fmt(w)} mm")
            return out
    if fill >= 0.95:
        out.update(kind="block", thickness_mm=round(t, 2),
                   words=f"Block {_fmt(length)} × {_fmt(w)} × {_fmt(t)} mm")
        return out
    return None


# ---------------------------------------------------------------------------
# Contacts between bodies
# ---------------------------------------------------------------------------


def _box_overlap(a: Body, b: Body, tol: float) -> Optional[tuple[np.ndarray, np.ndarray]]:
    lo = np.maximum(a.lo, b.lo) - tol
    hi = np.minimum(a.hi, b.hi) + tol
    if np.any(lo > hi):
        return None
    return lo, hi


def _region_faces(body: Body, lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, float]:
    """Faces of the body whose triangle box reaches into the box, and their area."""
    m = body.mesh
    if m is None:
        return np.zeros(0, dtype=np.int64), 0.0
    tri = m.triangles
    hit = np.nonzero(np.all(tri.max(axis=1) >= lo, axis=1) & np.all(tri.min(axis=1) <= hi, axis=1))[0]
    return hit, float(m.area_faces[hit].sum()) if len(hit) else 0.0


def _region_points(body: Body, hit: np.ndarray, total: float, lo: np.ndarray, hi: np.ndarray,
                   seed: int) -> tuple[np.ndarray, int]:
    """Points sampled uniformly on those faces that fall inside the box.

    Returns (points inside the box, total points drawn).
    """
    m = body.mesh
    if m is None or len(hit) == 0 or total <= 0:
        return np.zeros((0, 3)), 0
    tri = m.triangles
    rng = np.random.default_rng(seed)
    kept: list[np.ndarray] = []
    drawn = 0
    probs = m.area_faces[hit] / total
    for _ in range(_SAMPLE_ROUNDS):
        pick = rng.choice(len(hit), size=_SAMPLE_POINTS, p=probs)
        r = rng.random((_SAMPLE_POINTS, 2))
        flip = r.sum(axis=1) > 1
        r[flip] = 1 - r[flip]
        t3 = tri[hit[pick]]
        pts = t3[:, 0] + r[:, :1] * (t3[:, 1] - t3[:, 0]) + r[:, 1:] * (t3[:, 2] - t3[:, 0])
        drawn += _SAMPLE_POINTS
        inside = np.all(pts >= lo, axis=1) & np.all(pts <= hi, axis=1)
        kept.append(pts[inside])
        if sum(len(k) for k in kept) >= _MIN_REGION_POINTS:
            break
    return np.concatenate(kept) if kept else np.zeros((0, 3)), drawn


def _patch_shape(points: np.ndarray) -> tuple[float, float, float, float]:
    """(length, width, outline perimeter, outline area) of a contact patch, in its own plane."""
    if len(points) < 3:
        return 0.0, 0.0, 0.0, 0.0
    from shapely.geometry import MultiPoint

    c = points - points.mean(axis=0)
    try:
        _, _, vt = np.linalg.svd(c, full_matrices=False)
    except np.linalg.LinAlgError:
        return 0.0, 0.0, 0.0, 0.0
    uv = c @ vt[:2].T
    hull = MultiPoint([tuple(p) for p in uv]).convex_hull
    if hull.geom_type != "Polygon":
        length = float(hull.length) if hull.geom_type == "LineString" else 0.0
        return length, 0.0, 2 * length, 0.0
    a, b = _rect_dims(hull)
    return a, b, float(hull.length), float(hull.area)


def contact_between(a: Body, b: Body, *, seed: int = 0) -> Optional[dict]:
    """Where two bodies touch, nearly touch or overlap; None when they are apart.

    Points are sampled on whichever body has less surface in the box the two
    share; each point's distance to the other body (its faces in that box) says
    touching (within 0.05 mm) or a gap (within 0.5 mm). Points further away are
    tested for being inside the other body: an overlap.
    """
    box = _box_overlap(a, b, NEAR_TOL_MM)
    if box is None or a.mesh is None or b.mesh is None:
        return None
    lo, hi = box
    hit_a, area_a = _region_faces(a, lo, hi)
    hit_b, area_b = _region_faces(b, lo, hi)
    if area_a == 0 or area_b == 0:
        return None
    if area_a <= area_b:
        src, hit, area, target, t_hit = a, hit_a, area_a, b, hit_b
    else:
        src, hit, area, target, t_hit = b, hit_b, area_b, a, hit_a
    pts, drawn = _region_points(src, hit, area, lo, hi, seed)
    target_mesh = target.mesh
    if len(pts) == 0 or target_mesh is None:
        return None
    try:
        near_faces = _submesh(target_mesh, t_hit)
        _closest, dist, _tri = trimesh.proximity.closest_point(near_faces, pts)
    except Exception:
        logger.warning("contact distance failed between bodies %s and %s", a.index, b.index, exc_info=True)
        return None
    dist = np.asarray(dist, dtype=np.float64)
    touch = dist <= TOUCH_TOL_MM
    near = (dist > TOUCH_TOL_MM) & (dist <= NEAR_TOL_MM)
    over = np.zeros(len(pts), dtype=bool)
    far = np.nonzero(dist > NEAR_TOL_MM)[0]
    if len(far) and target.closed:
        probe = far[np.linspace(0, len(far) - 1, num=min(256, len(far))).astype(np.int64)]
        try:
            inside = np.asarray(target_mesh.contains(pts[probe]), dtype=bool)
        except Exception:
            inside = np.zeros(len(probe), dtype=bool)
        # scale the probed share back to all the far points
        if np.any(inside):
            share = float(np.mean(inside))
            pick = far[np.argsort(-dist[far])][: int(round(share * len(far)))]
            over[pick] = True
    joined = touch | near | over
    if not np.any(joined):
        return None
    patch = pts[touch | near] if np.any(touch | near) else pts[joined]
    length, width, perim, hull_area = _patch_shape(patch)
    est_area = float(np.sum(touch | near)) / max(drawn, 1) * area
    if np.sum(over) > 0.05 * np.sum(joined):
        kind = "overlap"
        depth = float(dist[over].max())
    elif np.any(touch):
        kind = "touching"
        depth = None
    else:
        kind = "near"
        depth = None
    gap = float(dist[near].min()) if kind == "near" else (0.0 if kind == "touching" else None)
    return {
        "a": a.index, "b": b.index, "type": kind,
        "gap_mm": round(gap, 3) if gap is not None else None,
        "overlap_mm": round(depth, 3) if depth is not None else None,
        "area_mm2": round(est_area, 1),
        "patch_mm": [round(length, 1), round(width, 1)],
        "outline_mm": round(perim, 1),
        "ring": bool(hull_area > 0 and est_area < 0.6 * hull_area),
    }


def _thinnest(body: Body) -> float:
    s = body.stock or {}
    if s.get("thickness_mm"):
        return float(s["thickness_mm"])
    return float(np.min(body.hi - body.lo))


def _weld_like(c: dict, a: Body, b: Body) -> bool:
    """A narrow joint (a plate edge on a face, a tube end on a tube) rather than a broad seat."""
    if c["type"] == "overlap":
        return False
    width = c["patch_mm"][1]
    return bool(c["ring"] or width <= 1.5 * min(_thinnest(a), _thinnest(b)) + TOUCH_TOL_MM)


# ---------------------------------------------------------------------------
# The whole file
# ---------------------------------------------------------------------------


def _design_key(b: Body) -> tuple:
    """Bodies of the same shape (same volume, area and box sides, wherever they sit)."""
    if b.key is not None:
        return ("given", *b.key)
    ext = np.sort(b.hi - b.lo)
    if b.stock and b.stock.get("box_mm"):
        ext = np.sort(np.asarray(b.stock["box_mm"], dtype=float))
    vol = round(b.volume, -1) if b.volume > 1000 else round(b.volume, 1)
    return (bool(b.closed), vol, round(b.area, -1) if b.area > 1000 else round(b.area, 1),
            *[round(float(e), 0) for e in ext])


def _count_words(counts: dict[Any, int]) -> str:
    parts = []
    for kind, n in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        one, many = _PLURAL.get(kind, _PLURAL[None])
        parts.append(f"{n} {one if n == 1 else many}")
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


_MAX_FACE_RANGES = 4000  # per body; past it the 3D view lights the first runs only


def _body_record(b: Body, design_counts: dict[int, int], design_first: dict[int, int]) -> dict:
    view = b.view_faces if b.view_faces is not None else b.faces
    runs = _ranges(view)
    rec = {
        "id": b.index,
        "label": f"Body {b.index}",
        "name": b.name,
        "faces": runs[:_MAX_FACE_RANGES],
        "faces_truncated": len(runs) > _MAX_FACE_RANGES,
        "face_count": int(len(view)),
        "closed": b.closed,
        "voids": b.voids,
        "volume_mm3": round(b.volume, 1),
        "surface_area_mm2": round(b.area, 1),
        "bbox_mm": [round(float(d), 2) for d in (b.hi - b.lo)],
        "bbox_min": [round(float(d), 3) for d in b.lo],
        "bbox_max": [round(float(d), 3) for d in b.hi],
        "centroid": [round(float(d), 3) for d in b.centroid],
        "stock": b.stock,
        "shape": (b.stock or {}).get("words") or f"Shaped part {' × '.join(_fmt(float(d)) for d in sorted(b.hi - b.lo, reverse=True))} mm",
        "design": b.design,
        "same_as": design_first[b.design] if design_first[b.design] != b.index else None,
        "copies": design_counts[b.design],
    }
    rec.update(b.extra)
    return rec


def _non_manifold_edges(mesh: trimesh.Trimesh) -> int:
    try:
        return int(np.sum(np.bincount(mesh.edges_unique_inverse) > 2))
    except Exception:
        return 0


def describe(mesh: trimesh.Trimesh, *, names: Optional[dict[int, str]] = None,
             product_tree: Optional[dict] = None, time_budget_sec: float = 20.0,
             bodies: Optional[list[Body]] = None, single_detail: bool = True) -> dict:
    """What the file holds, in the engine's words and in plain words.

    ``names`` maps body id -> product name read from a STEP product tree, when the
    caller has one; ``product_tree`` is its summary (parts, designs). Geometry
    decides everything else. ``single_detail=False`` answers a one-shell file at
    once (no stock reading), for the per-upload check.
    """
    started = time.monotonic()
    deadline = started + max(1.0, float(time_budget_sec))
    info: dict[str, Any] = {}
    if bodies is None:
        if not single_detail:
            _labels, count = shell_labels(mesh)
            if count <= 1:
                closed = bool(mesh.is_watertight)
                return {"version": 1, "kind": "single_solid", "body_count": 1 if count else 0,
                        "shells": count, "all_closed": closed,
                        "summary": "One solid body." if closed else "One body, not a closed solid."}
        bodies, info = split_bodies(mesh)
    out: dict[str, Any] = {"version": 1, "body_count": len(bodies), "shells": info.get("shells")}
    if not bodies:
        if info.get("too_many_shells") or info.get("too_many_bodies"):
            n = info.get("too_many_bodies") or info.get("shells")
            out.update(kind="many_bodies", body_count=n,
                       summary=f"This file holds {n:,} separate pieces, too many to check one by one "
                               f"(the limit is {max_bodies()}). It may be unmerged triangles or a scan.")
        else:
            out.update(kind="empty", summary="The file holds no surfaces.")
        return out
    all_closed = all(b.closed for b in bodies)
    out["all_closed"] = all_closed
    if len(bodies) == 1:
        b = bodies[0]
        if single_detail and b.closed and b.mesh is not None and time.monotonic() < deadline:
            b.stock = stock_of(b.mesh, b.volume)
        if b.voids:
            out.update(kind="single_solid_with_voids",
                       summary=f"One solid with {b.voids} sealed internal void{'s' if b.voids != 1 else ''}.")
        else:
            out.update(kind="single_solid", summary="One solid body." if b.closed else "One body, not a closed solid.")
        out["stock"] = b.stock
        return out
    # Closed bodies that share an edge where they touch: as one mesh it isn't a
    # closed solid, but every body on its own is.
    out["bodies_share_edges"] = bool(all_closed and _non_manifold_edges(mesh) > 0)

    for b in bodies:
        if names and b.index in names:
            b.name = names[b.index]
        if b.closed and b.mesh is not None and time.monotonic() < deadline:
            try:
                b.stock = stock_of(b.mesh, b.volume)
            except Exception:
                logger.warning("stock reading failed for body %s", b.index, exc_info=True)
    # identical shapes share one design (checked once, counted per copy)
    keys: dict[tuple, int] = {}
    for b in bodies:
        b.design = keys.setdefault(_design_key(b), len(keys) + 1)
    design_counts: dict[int, int] = {}
    design_first: dict[int, int] = {}
    for b in bodies:
        design_counts[b.design] = design_counts.get(b.design, 0) + 1
        design_first.setdefault(b.design, b.index)

    contacts: list[dict] = []
    pairs_checked = 0
    contacts_complete = True
    for i, a in enumerate(bodies):
        for b in bodies[i + 1:]:
            if _box_overlap(a, b, NEAR_TOL_MM) is None:
                continue
            if pairs_checked >= _MAX_CONTACT_PAIRS or time.monotonic() > deadline:
                contacts_complete = False
                continue
            pairs_checked += 1
            try:
                c = contact_between(a, b, seed=a.index * 1009 + b.index)
            except Exception:
                logger.warning("contact check failed", exc_info=True)
                c = None
            if c is not None:
                c["weld_like"] = _weld_like(c, a, b)
                contacts.append(c)

    # contact groups
    parent = {b.index: b.index for b in bodies}

    def root(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for c in contacts:
        ra, rb = root(c["a"]), root(c["b"])
        if ra != rb:
            parent[ra] = rb
    groups: dict[int, list[int]] = {}
    for b in bodies:
        groups.setdefault(root(b.index), []).append(b.index)

    stock_n = sum(1 for b in bodies if b.stock and b.stock.get("kind") in STOCK_KINDS)
    kinds: dict[Any, int] = {}
    for b in bodies:
        kind_of: Any = (b.stock or {}).get("kind")
        kinds[kind_of] = kinds.get(kind_of, 0) + 1
    joints = [c for c in contacts]
    weldment = (
        all_closed and bool(joints)
        and len(groups) == 1
        and all(c["weld_like"] for c in joints)
        and stock_n >= 0.75 * len(bodies)
    )
    n = len(bodies)
    named = sorted({b.name for b in bodies if b.name})
    what = _count_words(kinds)
    if named and all(b.name for b in bodies):
        # a product tree names its parts better than their shapes do
        by_name: dict[str, int] = {}
        for b in bodies:
            label = str(b.name)
            by_name[label] = by_name.get(label, 0) + 1
        what = ", ".join(f"{k} × {v}" for k, v in sorted(by_name.items(), key=lambda kv: (-kv[1], kv[0])))
    if weldment:
        long_n = sum(v for k, v in kinds.items() if k in LONG_KINDS)
        noun = "welded frame" if long_n >= 2 and long_n * 2 >= n else "welded fabrication"
        weld_mm = sum(c["outline_mm"] for c in joints)
        out.update(
            kind="weldment",
            summary=f"This file holds {n} separate bodies: likely a {noun} of {what}.",
            joints={
                "count": len(joints),
                "weld_length_mm_estimate": round(weld_mm, 0),
                "words": (f"{len(joints)} joint{'s' if len(joints) != 1 else ''} where members touch; "
                          f"about {weld_mm:,.0f} mm of weld if each is welded all round (an estimate "
                          f"from the outline of each contact, not a weld spec)."),
            },
            route=["cut", "prep", "weld", "finish"],
        )
    elif not contacts and not contacts_complete:
        out.update(
            kind="bodies",
            summary=(f"This file holds {n} separate bodies ({what}); whether they touch wasn't "
                     "measured in the time this check has."),
        )
    elif not contacts and contacts_complete:
        same = len({b.design for b in bodies}) == 1
        out.update(
            kind="separate_bodies",
            summary=(f"This file holds {n} separate bodies that don't touch: "
                     f"{'%d identical %s' % (n, _PLURAL.get(bodies[0].stock and bodies[0].stock.get('kind'), _PLURAL[None])[1]) if same else what}."),
        )
    else:
        touching = sum(len(g) for g in groups.values() if len(g) > 1)
        if product_tree and named:
            lead = (f"an assembly of {len(named)} design{'s' if len(named) != 1 else ''}, "
                    "named in the file's product tree")
        elif named and len(named) > 1:
            lead = f"an assembly of {len(named)} named parts"
        elif n == 2 and touching == 2:
            lead = "likely an assembly, or a part with its fixture"
        else:
            lead = "likely an assembly of separate parts"
        apart = n - touching
        tail = f"; {apart} of them touch nothing" if apart and touching else ""
        out.update(
            kind="assembly",
            summary=f"This file holds {n} bodies that touch: {lead} ({what}){tail}.",
        )
    out["bodies"] = [_body_record(b, design_counts, design_first) for b in bodies]
    out["designs"] = len(design_counts)
    out["contacts"] = contacts
    out["contacts_complete"] = contacts_complete
    if product_tree:
        out["product_tree"] = product_tree
    out["elapsed_sec"] = round(time.monotonic() - started, 2)
    out["basis"] = (
        "Measured from the file's mesh: bodies are closed skins (a skin inside another "
        "is a sealed void); stock shapes from each body's oriented box and three "
        "sections along its length; contacts from points sampled where bodies meet."
    )
    return out


@dataclass(frozen=True)
class BodyCount:
    bodies: int          # solid bodies (sealed voids don't count)
    all_closed: bool     # every body is a closed skin on its own
    share_edges: bool    # closed bodies that share an edge where they touch


def body_count(mesh: trimesh.Trimesh) -> BodyCount:
    """How many bodies, without describing them: cheap, for the universal checks.

    A one-shell mesh answers at once.
    """
    _labels, count = shell_labels(mesh)
    if count <= 1:
        return BodyCount(count, bool(mesh.is_watertight), False)
    bodies, info = split_bodies(mesh, with_meshes=False)
    if not bodies:
        return BodyCount(int(info.get("too_many_bodies") or info.get("shells") or 0), False, False)
    closed = all(b.closed for b in bodies)
    shared = len(bodies) > 1 and closed and _non_manifold_edges(mesh) > 0
    return BodyCount(len(bodies), closed, bool(shared))

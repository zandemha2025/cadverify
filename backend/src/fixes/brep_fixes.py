"""Geometry edits ScaleCAD can apply itself, on a COPY of a part's source file.

Runs inside a dedicated, killable ``spawn`` worker (see ``cad_fix_service``):
gmsh keeps one process-global, non-thread-safe OpenCASCADE context and its
boolean/fillet calls are uninterruptible C, so the only safe bound is a hard
wall-clock kill of a single-use process. Every function here is pure: bytes in,
``FixOutcome`` out. The caller's bytes are never written back anywhere; the
edited copy is returned as new bytes and the API layer re-checks it with the
real engine before anything is shown as fixed.

What is here, and why only this (measured in the round-6 spike on the repo's
real parts, see ``cad_fix_service`` for the numbers):

* ``fillet_inside_corners``: B-rep (STEP/IGES). Finds the B-rep edges whose
  tessellation the engine reads as sharp concave edges (concave, normals
  turning more than 30 degrees: every edge ``check_internal_radii`` and
  ``check_fillet_requirements`` can flag) and rounds them with OpenCASCADE's
  fillet at the radius the rule asks for.
* ``drain_holes``: B-rep and STL. A sealed cavity (an inner shell of the
  solid, or an inner watertight body of a mesh) gets a drain hole from its
  lowest point (file -Z is the build direction) and a vent from its highest
  point, each straight through the thinnest outer wall that a full-diameter
  probe crosses cleanly. B-rep uses OCC boolean cut; STL uses manifold3d.
* ``heal_brep``: B-rep. OCC shape healing (sew faces, fix small edges/faces,
  make solids) for a file whose faces were exported unsewn.

Draft (``add_draft``) lives in ``draft_ocp`` because gmsh has no draft API; it
needs the full OCP bindings and is only offered when they import.
"""
from __future__ import annotations

import math
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import numpy as np

from src.parsers.sigpipe import ignore_sigpipe

# Engine definition of a sharp inside edge (context.inside_corners and
# check_fillet_requirements start from it): a concave mesh edge whose face
# normals turn by more than 30 degrees.
SHARP_CONCAVE_DEG = 30.0
_BREP_SUFFIXES = (".step", ".stp", ".iges", ".igs")
_STEP_STAMP = re.compile(rb"(FILE_NAME\('[^']*',')\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(')")
_IGES_STAMP = re.compile(rb"15H\d{8}\.\d{6}")
# OCC numbers each STEP product it writes in a process ("... translator 7.8 2").
_STEP_PRODUCT = re.compile(rb"(Open CASCADE STEP translator [0-9.]+ )\d+")


class FixRefused(Exception):
    """The fix does not apply to this geometry; ``str(exc)`` is user-facing."""


@dataclass
class FixOutcome:
    """Worker result. ``data`` is the edited copy, or None when nothing was made."""

    applied: bool
    data: bytes | None
    suffix: str
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# gmsh session helpers
# ---------------------------------------------------------------------------


def _gmsh():
    import gmsh

    return gmsh


class _Session:
    """One gmsh model loaded from CAD bytes; always finalized."""

    def __init__(self, data: bytes, suffix: str):
        self.data = data
        self.suffix = suffix
        self.finalized = False
        self.tmpdir = tempfile.TemporaryDirectory(prefix="cadfix-")

    def __enter__(self):
        from src.parsers.step_mesher import _configure_cad_import, _import_cad_shapes

        gmsh = _gmsh()
        path = os.path.join(self.tmpdir.name, f"source{self.suffix}")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(self.data)
        gmsh.initialize(interruptible=False)
        ignore_sigpipe()  # gmsh just reset it to terminate the process
        gmsh.option.setNumber("General.Terminal", 0)
        _configure_cad_import(path)
        gmsh.model.add("fix")
        try:
            _import_cad_shapes(path)
            gmsh.model.occ.synchronize()
        except Exception as exc:
            raise FixRefused("The stored file could not be read as CAD geometry.") from exc
        return self

    def __exit__(self, *exc):
        try:
            if not self.finalized:
                _gmsh().finalize()
        finally:
            self.tmpdir.cleanup()
        return False

    def write(self, suffix: str, expected_mm3: float) -> tuple[bytes, str, str | None]:
        """Write the edited solid and prove it reads back as the same one solid.

        Ends the editing session. Returns ``(bytes, suffix, note)``. IGES stores
        faces, not solids, and an edited IGES does not always sew back closed;
        then the copy is written as STEP instead and the note says so. A file
        that reads back as anything but one solid of the same volume is never
        returned. The read-back runs in a fresh gmsh session, like an upload.
        """
        gmsh = _gmsh()
        candidates = [suffix] + ([".step"] if suffix in (".iges", ".igs") else [])
        paths = []
        for out in candidates:
            path = os.path.join(self.tmpdir.name, f"fixed{out}")
            gmsh.write(path)
            paths.append((out, path))
        gmsh.finalize()
        self.finalized = True
        for out, path in paths:
            if _reads_back_as(path, expected_mm3):
                note = None if out == suffix else (
                    "The edited solid didn't read back closed from IGES, so the fixed copy is STEP.")
                return _deterministic(Path(path).read_bytes(), out), out, note
        raise FixRefused("The edited solid doesn't read back from the written file as one closed solid.")


def _reads_back_as(path: str, expected_mm3: float) -> bool:
    from src.parsers.step_mesher import _configure_cad_import, _import_cad_shapes

    gmsh = _gmsh()
    gmsh.initialize(interruptible=False)
    ignore_sigpipe()  # gmsh just reset it to terminate the process
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        _configure_cad_import(path)
        gmsh.model.add("readback")
        _import_cad_shapes(path)
        gmsh.model.occ.synchronize()
        vols = gmsh.model.occ.getEntities(3)
        if len(vols) != 1:
            return False
        got = float(gmsh.model.occ.getMass(3, vols[0][1]))
        return abs(got - expected_mm3) <= 1e-3 * max(abs(expected_mm3), 1.0)
    except Exception:
        return False
    finally:
        gmsh.finalize()


def _deterministic(data: bytes, suffix: str) -> bytes:
    """Drop the writer's wall-clock stamp so the same fix makes the same bytes.

    The fixed copy is addressed by its SHA-256; a retry must land on the same
    part, not a new one per second.
    """
    if suffix in (".step", ".stp"):
        data = _STEP_STAMP.sub(rb"\g<1>2000-01-01T00:00:00\g<2>", data, count=1)
        return _STEP_PRODUCT.sub(rb"\g<1>1", data)
    if suffix in (".iges", ".igs"):
        return _IGES_STAMP.sub(b"15H20000101.000000", data)
    return data


def _single_volume() -> int:
    gmsh = _gmsh()
    vols = gmsh.model.occ.getEntities(3)
    if not vols:
        raise FixRefused("The file has no closed solid to edit.")
    if len(vols) > 1:
        raise FixRefused(
            f"The file holds {len(vols)} solids. ScaleCAD edits one solid at a time."
        )
    return vols[0][1]


def _volume_mm3(tag: int) -> float:
    return float(_gmsh().model.occ.getMass(3, tag))


def _mesh_brep(size_divisor: float = 60.0, uniform: bool = False):
    """Tessellate the current model like the engine does.

    ``uniform=False`` is the engine's primary rung (gmsh default 2D algorithm,
    12 points per circle); ``uniform=True`` is its periodic-surface recovery rung
    (MeshAdapt, no curvature refinement), used when the primary rung crashed the
    worker on this file. Returns ``(trimesh, line_edges)`` where ``line_edges``
    maps a sorted mesh-vertex pair to the B-rep curve it lies on.
    """
    import trimesh

    gmsh = _gmsh()
    xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
    diag = math.dist((xmin, ymin, zmin), (xmax, ymax, zmax))
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0 if uniform else 12)
    if uniform:
        gmsh.option.setNumber("Mesh.Algorithm", 1)
    gmsh.option.setNumber("Mesh.MeshSizeMax", min(max(diag / size_divisor, 0.05), 50.0))
    gmsh.model.mesh.generate(2)
    tags, coords, _ = gmsh.model.mesh.getNodes()
    index = {int(t): i for i, t in enumerate(tags)}
    verts = np.asarray(coords, dtype=np.float64).reshape(-1, 3)
    tris = []
    for _dim, surf in gmsh.model.getEntities(2):
        etypes, _etags, enodes = gmsh.model.mesh.getElements(2, surf)
        for et, conn in zip(etypes, enodes):
            if et == 2:
                tris.append(np.array([index[int(n)] for n in conn], dtype=np.int64).reshape(-1, 3))
    if not tris:
        raise FixRefused("The solid could not be tessellated to find its edges.")
    # Weld coincident nodes (periodic seams can carry duplicates), keeping the
    # node -> vertex map so curve edges still resolve after the weld.
    tol = max(diag * 1e-7, 1e-9)
    _keys, first, weld = np.unique(np.round(verts / tol).astype(np.int64), axis=0,
                                   return_index=True, return_inverse=True)
    weld = weld.reshape(-1)
    faces = weld[np.vstack(tris)]
    faces = faces[(faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])]
    mesh = trimesh.Trimesh(verts[first], faces, process=False)
    line_edges: dict[tuple[int, int], int] = {}
    for _dim, curve in gmsh.model.getEntities(1):
        etypes, _etags, enodes = gmsh.model.mesh.getElements(1, curve)
        for et, conn in zip(etypes, enodes):
            if et != 1:
                continue
            pairs = weld[np.array([index[int(n)] for n in conn], dtype=np.int64).reshape(-1, 2)]
            for a, b in pairs:
                if a != b:
                    line_edges[(min(a, b), max(a, b))] = curve
    return mesh, line_edges


def _exact_turn_deg(curve: int) -> float | None:
    """Angle between the two faces' exact normals at the curve's midpoint.

    Tessellation can make a tangent (already smooth) joint look creased; the
    B-rep normals can't. None when the curve doesn't join exactly two faces.
    """
    gmsh = _gmsh()
    up, _down = gmsh.model.getAdjacencies(1, curve)
    faces = sorted(set(int(f) for f in up))
    if len(faces) != 2:
        return None
    lo, hi = gmsh.model.getParametrizationBounds(1, curve)
    mid = gmsh.model.getValue(1, curve, [(lo[0] + hi[0]) / 2.0])
    normals = []
    for face in faces:
        uv = gmsh.model.getParametrization(2, face, list(mid))
        n = np.asarray(gmsh.model.getNormal(face, list(uv)), dtype=float)[:3]
        norm = float(np.linalg.norm(n))
        if norm < 1e-12:
            return None
        normals.append(n / norm)
    # Face orientation is unknown here: a tangent joint is parallel either way.
    return float(np.degrees(np.arccos(min(1.0, abs(float(np.dot(*normals)))))))


def _cutter_corner_rows(mesh) -> np.ndarray:
    """Adjacency rows on the inside corners a milling cutter leaves rounded.

    ``context.inside_corners``, the rule ``check_internal_radii`` counts: a
    pocket's vertical corners, not the edges along its floor (the flat end of
    the cutter cuts those sharp, so they aren't the corners the finding names).
    """
    from src.analysis.context import inside_corners

    diag = float(np.linalg.norm(mesh.extents)) if len(mesh.faces) else 0.0
    eps = max(1e-4, min(diag * 1e-4, 0.1))
    found = inside_corners(mesh, np.asarray(mesh.face_normals, dtype=np.float64),
                           np.asarray(mesh.face_adjacency, dtype=np.int64),
                           np.asarray(mesh.face_adjacency_angles, dtype=np.float64),
                           ~np.asarray(mesh.face_adjacency_convex, dtype=bool),
                           [np.asarray(f, dtype=int) for f in mesh.facets], eps)
    return np.asarray(found.edges, dtype=np.int64)


def sharp_concave_curves(threshold_deg: float = SHARP_CONCAVE_DEG, uniform: bool = False,
                         corners_only: bool = False) -> dict[int, dict]:
    """B-rep curves the engine would read as sharp inside corners.

    A curve qualifies when most of its tessellated edges are concave with face
    normals turning more than ``threshold_deg`` -- the exact mesh test the
    engine's corner checks run, applied per B-rep edge so the fix can name the
    edges to round -- and its two faces really meet at an angle (exact normals
    differ by more than 5 degrees), so a joint that is already smooth and only
    tessellates creased is never "rounded" again.

    ``corners_only``: only the corners a milling cutter leaves rounded
    (``_cutter_corner_rows``), so rounding a pocket's corners leaves its floor
    edges as drawn (a mating part may sit on that floor).
    """
    import trimesh

    gmsh = _gmsh()
    mesh, line_edges = _mesh_brep(uniform=uniform)
    try:
        if mesh.is_watertight:
            trimesh.repair.fix_normals(mesh)
        else:
            raise FixRefused("The solid's surface is not closed, so its inside corners can't be told apart.")
        edges = mesh.face_adjacency_edges
        angles = np.degrees(mesh.face_adjacency_angles)
        convex = mesh.face_adjacency_convex
        corner = None
        if corners_only:
            corner = np.zeros(len(edges), dtype=bool)
            corner[_cutter_corner_rows(mesh)] = True
    finally:
        gmsh.model.mesh.clear()
    stats: dict[int, list[float]] = {}  # [segments, sharp segments, worst turn]
    for row, ((a, b), ang, cvx) in enumerate(zip(edges, angles, convex)):
        curve = line_edges.get((min(a, b), max(a, b)))
        if curve is None:
            continue
        hit = (not bool(cvx)) and ang > threshold_deg and (corner is None or bool(corner[row]))
        s = stats.setdefault(curve, [0, 0, 0.0])
        s[0] += 1
        s[1] += int(hit)
        s[2] = max(s[2], float(ang) if hit else s[2])
    out = {}
    for curve, (n, hits, worst) in stats.items():
        if not n or hits / n < 0.5:
            continue
        try:
            exact = _exact_turn_deg(curve)
        except Exception:
            exact = None
        if exact is not None and exact < 5.0:
            continue  # tangent joint: smooth already, creased only in the mesh
        out[curve] = {"segments": n, "sharp_segments": hits, "max_turn_deg": round(worst, 1)}
    return out


# ---------------------------------------------------------------------------
# Fix: fillet sharp inside corners (B-rep)
# ---------------------------------------------------------------------------


def fillet_inside_corners(data: bytes, suffix: str, radius_mm: float, uniform: bool = False,
                          corners_only: bool = False) -> FixOutcome:
    """Round sharp inside edges on a copy.

    ``corners_only`` rounds only the corners a milling cutter leaves rounded (the
    ones the milling finding counts); otherwise every sharp concave edge
    (casting's fillets, floor edges included).
    """
    if suffix not in _BREP_SUFFIXES:
        raise FixRefused("Rounding inside corners needs a STEP or IGES file; an STL has no edges to round.")
    if not (0.05 <= radius_mm <= 25.0):
        raise FixRefused("Use a fillet radius from 0.05 to 25 mm.")
    gmsh = _gmsh()
    with _Session(data, suffix) as session:
        vol = _single_volume()
        before = _volume_mm3(vol)
        curves = sharp_concave_curves(uniform=uniform, corners_only=corners_only)
        if not curves:
            return FixOutcome(False, None, suffix, "No sharp inside corners were found on the B-rep edges.",
                              {"edges_found": 0})
        tags = sorted(curves)
        try:
            out = gmsh.model.occ.fillet([vol], tags, [radius_mm], removeVolume=True)
            gmsh.model.occ.synchronize()
        except Exception:
            return FixOutcome(
                False, None, suffix,
                f"OpenCASCADE could not round these {len(tags)} inside edges at {radius_mm:g} mm. "
                "The radius may be larger than a neighbouring face or wall.",
                {"edges_found": len(tags), "radius_mm": radius_mm},
            )
        vols = [t for d, t in out if d == 3] or [t for _d, t in gmsh.model.occ.getEntities(3)]
        if len(vols) != 1:
            return FixOutcome(False, None, suffix, "Rounding split the part into more than one solid.",
                              {"edges_found": len(tags)})
        after = _volume_mm3(vols[0])
        if not (after > 0 and math.isfinite(after)):
            return FixOutcome(False, None, suffix, "Rounding produced an empty solid.", {"edges_found": len(tags)})
        fixed, out_suffix, note = session.write(suffix, after)
    return FixOutcome(True, fixed, out_suffix, None, {
        "format_note": note,
        "edges_rounded": len(tags),
        "edges": "corners" if corners_only else "all",
        "radius_mm": radius_mm,
        "brep_volume_before_mm3": round(before, 3),
        "brep_volume_after_mm3": round(after, 3),
    })


# ---------------------------------------------------------------------------
# Fix: heal an unsewn / gappy B-rep (B-rep)
# ---------------------------------------------------------------------------


def heal_brep(data: bytes, suffix: str, tolerance_mm: float = 1e-3) -> FixOutcome:
    if suffix not in _BREP_SUFFIXES:
        raise FixRefused("Healing works on STEP or IGES B-rep files.")
    gmsh = _gmsh()
    with _Session(data, suffix) as session:
        solids_before = len(gmsh.model.occ.getEntities(3))
        faces_before = len(gmsh.model.occ.getEntities(2))
        try:
            gmsh.model.occ.healShapes(
                [], tolerance=tolerance_mm, fixDegenerated=True, fixSmallEdges=True,
                fixSmallFaces=True, sewFaces=True, makeSolids=True,
            )
            gmsh.model.occ.synchronize()
        except Exception:
            return FixOutcome(False, None, suffix, "OpenCASCADE shape healing stopped with an error.")
        vols = gmsh.model.occ.getEntities(3)
        if len(vols) != 1:
            reason = ("Healing could not close the faces into one solid; a face may be missing, "
                      "not just unsewn." if not vols else
                      f"Healing produced {len(vols)} solids, not one.")
            return FixOutcome(False, None, suffix, reason,
                              {"solids_before": solids_before, "solids_after": len(vols)})
        after = _volume_mm3(vols[0][1])
        if not (after > 0 and math.isfinite(after)):
            return FixOutcome(False, None, suffix, "Healing produced an empty solid.")
        fixed, out_suffix, note = session.write(suffix, after)
    return FixOutcome(True, fixed, out_suffix, None, {
        "format_note": note,
        "solids_before": solids_before,
        "solids_after": 1,
        "faces_before": faces_before,
        "tolerance_mm": tolerance_mm,
        "brep_volume_after_mm3": round(after, 3),
    })


# ---------------------------------------------------------------------------
# Fix: drain and vent holes into sealed cavities (B-rep and STL)
# ---------------------------------------------------------------------------


_HORIZONTAL = (
    np.array([1.0, 0.0, 0.0]), np.array([-1.0, 0.0, 0.0]),
    np.array([0.0, 1.0, 0.0]), np.array([0.0, -1.0, 0.0]),
)


def _perp_basis(d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ref = np.array([1.0, 0.0, 0.0]) if abs(d[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(d, ref)
    u /= np.linalg.norm(u)
    return u, np.cross(d, u)


def _probe_exit(part, start: np.ndarray, d: np.ndarray, radius: float):
    """Wall crossed by a straight hole of ``radius`` from ``start`` along ``d``.

    ``part`` is the full watertight mesh (outer skin + cavity skins). The axis and
    8 probes on the hole's rim must each cross exactly one wall: the cavity skin,
    then the outer skin, then open air. Returns ``(wall_mm, exit_distance)`` or
    None when the path hits anything else or the wall isn't a simple slab.
    """
    u, v = _perp_basis(d)
    offsets = [np.zeros(3)] + [radius * 0.98 * (math.cos(a) * u + math.sin(a) * v)
                               for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)]
    walls, exits = [], []
    for off in offsets:
        origin = start + off
        locs, _ray, _tri = part.ray.intersects_location([origin], [d], multiple_hits=True)
        if len(locs) != 2:
            return None
        dist = np.sort(np.linalg.norm(locs - origin, axis=1))
        walls.append(float(dist[1] - dist[0]))
        exits.append(float(dist[1]))
    wall = float(np.median(walls))
    if max(walls) - min(walls) > max(0.5 * wall, 0.2):
        return None
    return wall, max(exits)


def _plan_hole(part, low_or_high: np.ndarray, role: str, radius: float, cavity_height: float):
    """Shortest clean exit for a drain (from the lowest point) or vent (highest).

    Candidates: straight down (drain) / up (vent) from the extreme point, and
    sideways at the extreme point's height shifted by the radius so the hole's
    edge sits flush with the cavity floor (ceiling). The thinnest clean wall
    wins; ties keep the vertical exit.
    """
    up = np.array([0.0, 0.0, 1.0])
    sign = -1.0 if role == "drain" else 1.0
    vertical = up * sign
    candidates = [(low_or_high - vertical * radius * 0.25, vertical)]
    if cavity_height >= 2.05 * radius:
        lifted = low_or_high - vertical * radius * 1.02
        candidates += [(lifted, d) for d in _HORIZONTAL]
    best = None
    for start, d in candidates:
        probe = _probe_exit(part, start, d, radius)
        if probe is None:
            continue
        wall, exit_dist = probe
        if best is None or wall < best[2] - 1e-6:
            best = (start, d, wall, exit_dist)
    return best


def _hole_starts(cavity, radius: float):
    """Drain start (lowest point) and vent start (highest point) inside a cavity.

    A flat floor/ceiling picks the triangle centroid nearest the region's area
    centroid, then the start is lifted (lowered) by the radius so a sideways
    hole sits flush with the floor (ceiling) instead of half under it.
    """
    z = cavity.vertices[:, 2]
    tol = max(1e-3, 1e-4 * float(np.ptp(z) or 1.0))
    starts = []
    for sign in (-1.0, 1.0):
        level = z.min() if sign < 0 else z.max()
        faces = np.where(np.all(np.abs(cavity.vertices[cavity.faces][:, :, 2] - level) <= tol, axis=1))[0]
        if len(faces):
            cent = cavity.triangles_center[faces]
            w = cavity.area_faces[faces]
            target = (cent * w[:, None]).sum(0) / max(w.sum(), 1e-12)
            pt = cent[np.argmin(np.linalg.norm(cent - target, axis=1))]
        else:
            pt = cavity.vertices[np.argmin(z) if sign < 0 else np.argmax(z)]
        pt = pt.copy()
        starts.append(pt)
    return starts  # [lowest, highest]


def _cavity_meshes_from_mesh(mesh):
    """Split ``mesh`` into its outer body and the sealed cavities inside it.

    Nesting depth decides: a shell inside exactly one other shell is a cavity;
    a shell inside two (an island sitting in a cavity) is refused, and two
    side-by-side outer bodies are separate parts, not a cavity. Each returned
    mesh is oriented the way a solid with voids must be: the outer skin's
    normals point out of the part, each cavity skin's into its void.
    """
    bodies = list(mesh.split(only_watertight=False))
    if len(bodies) < 2:
        return mesh, []
    if not all(body.is_watertight for body in bodies):
        raise FixRefused("Part of the surface is not closed, so a sealed cavity can't be located.")
    probes = [body.vertices[0] for body in bodies]
    depth = []
    for i, point in enumerate(probes):
        depth.append(sum(
            1 for j, other in enumerate(bodies)
            if j != i and bool(other.contains([point])[0])
        ))
    outer = [i for i, d in enumerate(depth) if d == 0]
    if len(outer) != 1:
        raise FixRefused(f"The file holds {len(outer)} separate bodies. ScaleCAD edits one solid at a time.")
    if any(d >= 2 for d in depth):
        raise FixRefused("A body sits loose inside a cavity. Drain holes would not free it.")
    main = bodies[outer[0]].copy()
    if main.volume < 0:
        main.invert()
    cavities = []
    for i, d in enumerate(depth):
        if d == 1:
            cav = bodies[i].copy()
            if cav.volume > 0:
                cav.invert()
            cavities.append(cav)
    return main, cavities


def _plan_all_holes(part_mesh, cavities, diameter: float, per_cavity: int):
    radius = diameter / 2.0
    plans: list[dict] = []
    skipped: list[dict] = []
    for ci, cav in enumerate(cavities):
        low, high = _hole_starts(cav, radius)
        height = float(np.ptp(cav.vertices[:, 2]))
        roles = [("drain", low)] + ([("vent", high)] if per_cavity >= 2 else [])
        for role, pt in roles:
            best = _plan_hole(part_mesh, pt, role, radius, height)
            if best is None and role == "vent":
                skipped.append({"cavity": ci + 1, "role": role,
                                "reason": f"no straight, clean path for a {diameter:g} mm vent"})
                continue
            if best is None:
                return None, (f"No straight, clean path out of cavity {ci + 1} "
                              f"for a {diameter:g} mm drain hole.")
            start, d, wall, exit_dist = best
            plans.append({
                "cavity": ci + 1, "role": role,
                "start": [round(float(x), 4) for x in start],
                "direction": [int(round(float(x))) for x in d],
                "wall_mm": round(wall, 3),
                "length_mm": round(exit_dist, 3),
                "diameter_mm": diameter,
            })
    return (plans, skipped), None


def _cavity_meshes_from_brep(uniform: bool = False):
    """Tessellate the solid; return the full mesh and its inner (cavity) shells."""

    mesh, _edges = _mesh_brep(size_divisor=80.0, uniform=uniform)
    _gmsh().model.mesh.clear()
    mesh.merge_vertices()
    if not mesh.is_watertight:
        raise FixRefused("The solid's surface is not closed, so a sealed cavity can't be located.")
    main, cavities = _cavity_meshes_from_mesh(mesh)
    return mesh, cavities


def drain_holes(data: bytes, suffix: str, diameter_mm: float, per_cavity: int = 2,
                uniform: bool = False) -> FixOutcome:
    if not (0.5 <= diameter_mm <= 50.0):
        raise FixRefused("Use a drain-hole diameter from 0.5 to 50 mm.")
    if suffix == ".stl":
        return _drain_holes_stl(data, diameter_mm, per_cavity)
    if suffix not in _BREP_SUFFIXES:
        raise FixRefused("Drain holes need a STEP, IGES or STL file.")
    gmsh = _gmsh()
    with _Session(data, suffix) as session:
        vol = _single_volume()
        before = _volume_mm3(vol)
        loops, _surfs = gmsh.model.occ.getSurfaceLoops(vol)
        mesh, cavities = _cavity_meshes_from_brep(uniform)
        if not cavities:
            return FixOutcome(False, None, suffix, "No sealed cavity was found inside the solid.",
                              {"shells": len(loops)})
        planned, why = _plan_all_holes(mesh, cavities, diameter_mm, per_cavity)
        if planned is None:
            return FixOutcome(False, None, suffix, why, {"cavities": len(cavities)})
        plans, skipped = planned
        tools = []
        r = diameter_mm / 2.0
        for p in plans:
            s = np.array(p["start"])
            d = np.array(p["direction"], dtype=float)
            length = p["length_mm"] + r
            x, y, z = s
            dx, dy, dz = d * length
            tools.append((3, gmsh.model.occ.addCylinder(x, y, z, dx, dy, dz, r)))
        try:
            out, _map = gmsh.model.occ.cut([(3, vol)], tools, removeObject=True, removeTool=True)
            gmsh.model.occ.synchronize()
        except Exception:
            return FixOutcome(False, None, suffix, "OpenCASCADE could not cut the holes.", {"holes": plans})
        vols = [t for d, t in out if d == 3]
        if len(vols) != 1:
            return FixOutcome(False, None, suffix, "Cutting the holes split the part into more than one solid.",
                              {"holes": plans})
        after = _volume_mm3(vols[0])
        loops_after, _ = gmsh.model.occ.getSurfaceLoops(vols[0])
        if len(loops_after) != len(loops) - len(cavities):
            return FixOutcome(False, None, suffix, "The holes did not open every cavity to the outside.",
                              {"holes": plans, "shells_after": len(loops_after)})
        fixed, out_suffix, note = session.write(suffix, after)
    return FixOutcome(True, fixed, out_suffix, None, {
        "format_note": note,
        "cavities_opened": len(cavities),
        "holes": plans,
        "holes_skipped": skipped,
        "brep_volume_before_mm3": round(before, 3),
        "brep_volume_after_mm3": round(after, 3),
    })


def _drain_holes_stl(data: bytes, diameter_mm: float, per_cavity: int) -> FixOutcome:
    import manifold3d
    import trimesh

    from src.parsers.stl_parser import parse_stl_from_bytes

    mesh = parse_stl_from_bytes(data, "source.stl")
    if not mesh.is_watertight:
        raise FixRefused("The mesh is not closed, so a sealed cavity can't be located. Repair it first.")
    main, cavities = _cavity_meshes_from_mesh(mesh)
    if not cavities:
        return FixOutcome(False, None, ".stl", "No sealed cavity was found inside the mesh.")
    part = trimesh.util.concatenate([main, *cavities])
    planned, why = _plan_all_holes(part, cavities, diameter_mm, per_cavity)
    if planned is None:
        return FixOutcome(False, None, ".stl", why, {"cavities": len(cavities)})
    plans, skipped = planned

    def to_manifold(m):
        return manifold3d.Manifold(manifold3d.Mesh(
            vert_properties=np.asarray(m.vertices, dtype=np.float32),
            tri_verts=np.asarray(m.faces, dtype=np.uint32)))

    base = to_manifold(part)
    if base.status() != manifold3d.Error.NoError:
        return FixOutcome(False, None, ".stl", "The mesh is not a valid manifold solid for a boolean cut.")
    before = float(base.volume())
    r = diameter_mm / 2.0
    fine = max(32, int(math.ceil(2 * math.pi * r / 0.25)))
    last = "The boolean cut did not produce a valid solid."
    # The cut must survive the trip through STL, which stores no vertex
    # identity: the engine welds coincident corners on re-import. A hole rim
    # landing almost on an existing vertex can weld into an open seam, so a few
    # rim resolutions are tried and only a copy that re-imports closed and in
    # one piece is returned.
    for sections in dict.fromkeys((min(fine, 256), 64, 96, 48)):
        solid = base
        for p in plans:
            s = np.array(p["start"])
            d = np.array(p["direction"], dtype=float)
            cyl = trimesh.creation.cylinder(radius=r, segment=[s, s + d * (p["length_mm"] + r)], sections=sections)
            solid = solid - to_manifold(cyl)
        if solid.status() != manifold3d.Error.NoError or solid.is_empty():
            continue
        if len(solid.decompose()) != 1:
            last = "The cut left the mesh in several pieces."
            continue
        out = solid.to_mesh()
        fixed = trimesh.Trimesh(np.asarray(out.vert_properties)[:, :3], np.asarray(out.tri_verts), process=False)
        payload = cast(bytes, fixed.export(file_type="stl"))  # STL export: bytes
        back = parse_stl_from_bytes(payload, "fixed.stl")
        if not back.is_watertight or len(back.split(only_watertight=False)) != 1:
            last = "The cut mesh does not stay closed when written as STL."
            continue
        break
    else:
        return FixOutcome(False, None, ".stl", last, {"holes": plans})
    after = float(back.volume)
    return FixOutcome(True, payload, ".stl", None, {
        "cavities_opened": len(cavities),
        "holes": plans,
        "holes_skipped": skipped,
        "mesh_volume_before_mm3": round(before, 3),
        "mesh_volume_after_mm3": round(after, 3),
        "rim_sections": sections,
    })


# ---------------------------------------------------------------------------
# Worker entry
# ---------------------------------------------------------------------------


def run_fix(fix_id: str, data: bytes, suffix: str, params: dict) -> FixOutcome:
    """Picklable worker entry for the spawn subprocess."""
    suffix = suffix.lower()
    try:
        uniform = bool(params.get("_uniform_mesh"))
        if fix_id == "fillet_inside_corners":
            return fillet_inside_corners(data, suffix, float(params["radius_mm"]), uniform,
                                         corners_only=params.get("edges") == "corners")
        if fix_id == "drain_holes":
            return drain_holes(data, suffix, float(params["diameter_mm"]),
                               int(params.get("per_cavity", 2)), uniform)
        if fix_id == "heal_brep":
            return heal_brep(data, suffix, float(params.get("tolerance_mm", 1e-3)))
        if fix_id == "add_draft":
            from src.fixes.draft_ocp import add_draft

            return add_draft(data, suffix, float(params["angle_deg"]))
    except FixRefused as exc:
        return FixOutcome(False, None, suffix, str(exc))
    raise ValueError(f"unknown fix {fix_id!r}")

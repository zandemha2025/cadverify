"""Which way the part sits for a check: its build and pull direction.

The engine reads the analysed mesh's +Z as up. What depends on it:

* Printing (build direction): faces past a process's overhang limit need
  support (``check_overhangs``: FDM 45°, SLA 19°, DLP 30°, DMLS/SLM 45°,
  EBM 50°, DED/WAAM 60°; faces resting on the plate are exempt); large
  downward areas cup in a resin tank (SLA ``CUPPING_RISK``); a large flat area
  parallel to the plate can curl in metal powder beds (``RESIDUAL_STRESS_RISK``).
* Molding, casting and forging (the direction the tool opens): walls parallel
  to it need draft (``check_draft_angles``: injection molding and die casting
  1°, sand casting 3°, forging 5°) and anything that blocks the opening is an
  undercut (``check_undercuts_molding``).
* CNC setup access (``SETUP_ACCESS_UNVERIFIED``): whether the finding appears
  doesn't depend on it, but the faces it marks are the ones facing away from +Z.
* The work-area note ``BUILD_REORIENTATION_REQUIRED`` compares the file's own
  axes with a machine's.

What does not depend on it: work-area fit (the envelope checks and the machine
fit try the ways the part can sit), and every price. The cost model prices a
print at the lowest build height an enclosing box can take in the machine and
does not price support material; CNC stock, molds and castings are sized from
an enclosing box that doesn't depend on the file's axes.

A chosen orientation is a proper rotation ``R`` applied to the mesh before
analysis (``placed = R · file``; row 3 of ``R`` is the file direction that ends
up pointing up). A rotation by 90° steps is a signed permutation of the
coordinates, so it is exact: extents are permuted, volume and area are the
same, and the faces keep their order, so face indices still match the file's
own 3D view. Points the analysis reports (region centres, feature centroids,
centre of mass) are turned back into the file's coordinates; dimensions are
reported as placed (the third is the build height).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import numpy as np
import trimesh

# The analyzers' own limits (backend/src/analysis/processes/*). A test runs every
# analyzer and checks its OVERHANG / INSUFFICIENT_DRAFT findings against these.
OVERHANG_LIMIT_DEG: dict[str, float] = {
    "fdm": 45.0, "sla": 19.0, "dlp": 30.0, "dmls": 45.0, "slm": 45.0,
    "ebm": 50.0, "ded": 60.0, "waam": 60.0,
}
DRAFT_MIN_DEG: dict[str, float] = {
    "injection_molding": 1.0, "die_casting": 1.0, "sand_casting": 3.0, "forging": 5.0,
}

_SNAP = 1e-9
_ORTHO_TOL = 1e-6
_AXES = {"x": 0, "y": 1, "z": 2}
_AXIS_NAMES = ("X", "Y", "Z")


class OrientationError(ValueError):
    """The orientation asked for can't be used (shown to the caller as a 400)."""


def _rot_axis(axis: int, degrees: float) -> np.ndarray:
    """Rotation about a coordinate axis; exact for multiples of 90°."""
    quarter = degrees / 90.0
    if abs(quarter - round(quarter)) < 1e-12:
        k = int(round(quarter)) % 4
        c, s = (1.0, 0.0, -1.0, 0.0)[k], (0.0, 1.0, 0.0, -1.0)[k]
    else:
        r = math.radians(degrees)
        c, s = math.cos(r), math.sin(r)
    i, j = [a for a in range(3) if a != axis]
    if axis == 1:  # right-handed about Y: z→x is positive
        i, j = j, i
    m = np.eye(3)
    m[i, i], m[i, j], m[j, i], m[j, j] = c, -s, s, c
    return m


def rotation_from_turns(turns: Iterable[str]) -> np.ndarray:
    """Compose turns such as ``["x90", "z-90"]``, each about the placed axes, in order."""
    out = np.eye(3)
    for raw in turns:
        token = str(raw).strip().lower()
        if not token:
            continue
        axis = _AXES.get(token[0])
        try:
            deg = float(token[1:])
        except ValueError:
            axis = None
        if axis is None or not math.isfinite(deg) or abs(deg) > 3600:
            raise OrientationError(f"Unknown turn '{raw}'. Use x90, y-90, z180 and so on.")
        out = _rot_axis(axis, deg) @ out
    return out


def _unit(v) -> np.ndarray:
    a = np.asarray(v, dtype=float).reshape(-1)
    if a.shape != (3,) or not np.all(np.isfinite(a)):
        raise OrientationError("A direction needs three finite numbers.")
    n = float(np.linalg.norm(a))
    if n < 1e-12:
        raise OrientationError("A direction can't be zero.")
    a = a / n
    # Snap a direction that is an axis to that axis exactly.
    k = int(np.argmax(np.abs(a)))
    if abs(abs(a[k]) - 1.0) < 1e-9:
        e = np.zeros(3)
        e[k] = math.copysign(1.0, a[k])
        return e
    return a


def rotation_down(direction) -> np.ndarray:
    """The smallest rotation that puts the file direction ``direction`` straight down (-Z).

    An axis lands exactly: -Z stays, +Z turns 180° about X, ±X and ±Y turn 90°.
    """
    d = _unit(direction)
    target = np.array([0.0, 0.0, -1.0])
    c = float(d @ target)
    if c > 1 - 1e-15:
        return np.eye(3)
    if c < -1 + 1e-15:
        return _rot_axis(0, 180.0)
    if np.count_nonzero(d) == 1:  # ±X or ±Y: a quarter turn, exactly
        axis = 1 if d[0] else 0
        sign = (1 if d[0] > 0 else -1) if axis == 1 else (-1 if d[1] > 0 else 1)
        return _rot_axis(axis, 90.0 * sign)
    v = np.cross(d, target)
    s = float(np.linalg.norm(v))
    k = v / s
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + s * K + (1 - c) * (K @ K)


def _clean(m: np.ndarray) -> np.ndarray:
    """Validate a proper rotation; snap 0/±1 entries so 90° steps stay exact."""
    m = np.asarray(m, dtype=float)
    if m.shape != (3, 3) or not np.all(np.isfinite(m)):
        raise OrientationError("A rotation is a 3×3 matrix of finite numbers.")
    if np.max(np.abs(m @ m.T - np.eye(3))) > _ORTHO_TOL:
        raise OrientationError("That matrix is not a rotation (its rows must be perpendicular unit vectors).")
    if np.linalg.det(m) < 0:
        raise OrientationError("That matrix mirrors the part; an orientation can only turn it.")
    snapped = np.round(m)
    if np.max(np.abs(m - snapped)) < _SNAP:
        return snapped + 0.0  # signed permutation; +0.0 drops negative zeros
    u, _, vt = np.linalg.svd(m)
    r = u @ vt
    return np.where(np.abs(r) < 1e-15, 0.0, r)


def _axis_name(v: np.ndarray) -> str | None:
    k = int(np.argmax(np.abs(v)))
    if abs(abs(v[k]) - 1.0) > 1e-12:
        return None
    return ("+" if v[k] > 0 else "−") + _AXIS_NAMES[k]


def _fmt_dir(v: np.ndarray) -> str:
    return "(" + ", ".join(f"{c:.2f}".replace("-0.00", "0.00") for c in v) + ")"


@dataclass(frozen=True)
class Orientation:
    """A proper rotation from the file's coordinates to the placed part (+Z up)."""

    matrix: tuple[tuple[float, float, float], ...]

    @classmethod
    def of(cls, m) -> "Orientation":
        r = _clean(np.asarray(m, dtype=float))
        return cls(tuple(tuple(float(x) for x in row) for row in r))

    @property
    def R(self) -> np.ndarray:
        return np.array(self.matrix, dtype=float)

    @property
    def is_identity(self) -> bool:
        return bool(np.array_equal(self.R, np.eye(3)))

    @property
    def exact(self) -> bool:
        """A 90°-step rotation: every entry is 0 or ±1."""
        return bool(np.all(np.isin(self.R, (-1.0, 0.0, 1.0))))

    @property
    def up(self) -> np.ndarray:
        """The file direction that points up (+Z) once placed."""
        return self.R[2].copy()

    @property
    def key(self) -> str:
        """Canonical text for cache keys and record hashes."""
        return "rotation:" + ",".join(f"{v:.15g}" for row in self.matrix for v in row)

    @property
    def label(self) -> str:
        if self.is_identity:
            return "As in the file"
        up = _axis_name(self.up)
        if up is not None:
            return f"File {up} up"
        return f"Tilted: file direction {_fmt_dir(self.up)} up"

    def apply(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """A turned copy with the same faces in the same order. The file mesh is untouched."""
        return _turn(mesh, self.R)

    def unapply(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        return _turn(mesh, self.R.T)

    def to_file(self, point) -> list[float] | None:
        """A placed point back in the file's coordinates."""
        if point is None:
            return None
        p = np.asarray(point, dtype=float)
        if p.shape != (3,) or not np.all(np.isfinite(p)):
            return list(point) if point is not None else None
        return [float(c) for c in self.R.T @ p]

    def record(self, *, file_face_hash: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rotation": [list(row) for row in self.matrix],
            "up_in_file": [float(c) for c in self.up],
            "label": self.label,
            "exact": self.exact,
            "key": self.key,
            "points": "file",
            "note": (
                "Checked with the part turned so the file's "
                + (_axis_name(self.up) or _fmt_dir(self.up))
                + " points up: the build direction for printing and the direction the tool opens "
                "for molding and casting. Dimensions are as placed (the third is the height); "
                "region centres and centroids are in the file's own coordinates."
            ),
        }
        if file_face_hash:
            out["file_face_hash"] = file_face_hash
        return out


def _turn(mesh: trimesh.Trimesh, R: np.ndarray) -> trimesh.Trimesh:
    vertices = np.asarray(mesh.vertices, dtype=np.float64) @ R.T
    out = trimesh.Trimesh(vertices=vertices, faces=np.asarray(mesh.faces).copy(), process=False)
    out.metadata.update(dict(mesh.metadata or {}))
    return out


def parse_orientation(raw: Any) -> Optional[Orientation]:
    """An orientation from a request value, or None for the file's own.

    Accepted: a JSON object ``{"rotation": [[...], [...], [...]]}``,
    ``{"turns": ["x90", "z-90"]}`` or ``{"down": [x, y, z]}`` (that file
    direction on the plate; ``turns`` may follow), or the short forms
    ``rotation:r00,r01,…,r22``, ``turns:x90,z-90`` and ``down:x,y,z``.
    Empty, ``file`` and the identity mean the file's own orientation.
    """
    if raw is None:
        return None
    if isinstance(raw, Orientation):
        return None if raw.is_identity else raw
    spec: Any = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text.lower() in {"file", "identity", "none", "as-in-file"}:
            return None
        if text.startswith("{"):
            try:
                spec = json.loads(text)
            except ValueError as exc:
                raise OrientationError("The orientation isn't valid JSON.") from exc
        else:
            kind, _, rest = text.partition(":")
            kind = kind.strip().lower()
            parts = [p for p in rest.replace(";", ",").split(",") if p.strip()]
            if kind == "turns":
                spec = {"turns": parts}
            elif kind in {"down", "rotation"}:
                try:
                    nums = [float(p) for p in parts]
                except ValueError as exc:
                    raise OrientationError(f"The {kind} needs numbers.") from exc
                if kind == "down":
                    spec = {"down": nums}
                else:
                    if len(nums) != 9:
                        raise OrientationError("A rotation needs nine numbers, row by row.")
                    spec = {"rotation": [nums[0:3], nums[3:6], nums[6:9]]}
            else:
                raise OrientationError("Use rotation:…, turns:… or down:… for the orientation.")
    if not isinstance(spec, dict):
        raise OrientationError("The orientation must be an object.")
    unknown = set(spec) - {"rotation", "turns", "down", "label"}
    if unknown:
        raise OrientationError(f"Unknown orientation field(s): {', '.join(sorted(unknown))}.")
    if "rotation" in spec and ("down" in spec or "turns" in spec):
        raise OrientationError("Give a rotation, or down and turns, not both.")
    if "rotation" in spec:
        try:
            m = np.asarray(spec["rotation"], dtype=float)
        except (TypeError, ValueError) as exc:
            raise OrientationError("A rotation is a 3×3 matrix of numbers.") from exc
    else:
        m = rotation_down(spec["down"]) if spec.get("down") is not None else np.eye(3)
        turns = spec.get("turns") or []
        if isinstance(turns, str):
            turns = [t for t in turns.split(",")]
        if not isinstance(turns, (list, tuple)) or len(turns) > 24:
            raise OrientationError("Turns are a list such as [\"x90\", \"z-90\"].")
        m = rotation_from_turns(turns) @ m
    o = Orientation.of(m)
    return None if o.is_identity else o


def turn_points_to_file(orientation: Orientation | None, issues: Iterable) -> None:
    """Report region centres in file coordinates (in place, on fresh analyzer output)."""
    if orientation is None:
        return
    for issue in issues:
        rc = getattr(issue, "region_center", None)
        if rc is not None and len(rc) == 3:
            back = orientation.to_file(rc)
            issue.region_center = tuple(back) if back is not None else rc


def all_issues(universal_issues, process_scores) -> list:
    out = list(universal_issues or [])
    for ps in process_scores or []:
        out.extend(getattr(ps, "issues", []) or [])
    return out


def record_points_to_file(orientation: Orientation | None, result: dict) -> None:
    """Turn the serialized points of a placed analysis back into file coordinates."""
    if orientation is None or not isinstance(result, dict):
        return

    def back(p, digits):
        if isinstance(p, list) and len(p) == 3 and all(isinstance(c, (int, float)) for c in p):
            return [round(c, digits) for c in orientation.to_file(p)]
        return p

    geo = result.get("geometry")
    if isinstance(geo, dict) and "center_of_mass" in geo:
        geo["center_of_mass"] = back(geo["center_of_mass"], 2)
    for f in result.get("features") or []:
        if isinstance(f, dict) and "centroid" in f:
            f["centroid"] = back(f["centroid"], 3)
    for s in result.get("segments") or []:
        if isinstance(s, dict) and "centroid" in s:
            s["centroid"] = back(s["centroid"], 2)


# ──────────────────────────────────────────────────────────────────────────
# Ways to lay the part down, compared by the check's own rules
# ──────────────────────────────────────────────────────────────────────────
_SIDES: tuple[tuple[str, tuple[float, float, float]], ...] = (
    ("down-z", (0.0, 0.0, -1.0)),
    ("down+z", (0.0, 0.0, 1.0)),
    ("down-x", (-1.0, 0.0, 0.0)),
    ("down+x", (1.0, 0.0, 0.0)),
    ("down-y", (0.0, -1.0, 0.0)),
    ("down+y", (0.0, 1.0, 0.0)),
)


def placed_measures(placed: trimesh.Trimesh) -> dict[str, np.ndarray | float]:
    """The per-face arrays the check builds (``GeometryContext.build``), for a placed mesh."""
    normals = np.asarray(placed.face_normals, dtype=np.float64)
    with np.errstate(all="ignore"):
        cos_z = np.clip(normals @ np.array([0.0, 0.0, 1.0]), -1.0, 1.0)
        angles = np.degrees(np.arccos(cos_z))
    extents = placed.extents
    diag = 0.0 if extents is None or len(placed.faces) == 0 else float(np.linalg.norm(np.asarray(extents, dtype=np.float64)))
    return {
        "normals": normals,
        "angles": angles,
        "centroids": np.asarray(placed.triangles_center, dtype=np.float64),
        "areas": np.asarray(placed.area_faces, dtype=np.float64),
        "bbox_diag": diag,
    }


def _candidate(cid: str, basis: str, R: np.ndarray, mesh: trimesh.Trimesh, total_area: float,
               extra: dict | None = None) -> dict:
    from src.analysis.processes.checks import draft_sidewalls, overhang_faces

    o = Orientation.of(R)
    placed = o.apply(mesh)
    m = placed_measures(placed)
    angles, centroids, areas, normals = m["angles"], m["centroids"], m["areas"], m["normals"]
    lo, hi = placed.bounds
    ext = hi - lo
    z = centroids[:, 2] if len(centroids) else np.empty(0)
    z_tol = max(0.1, float(m["bbox_diag"]) * 1e-3)
    on_plate = (z <= float(z.min()) + z_tol) & (angles >= 175.0) if len(z) else np.zeros(0, bool)
    support = {}
    for proc, limit in OVERHANG_LIMIT_DEG.items():
        faces = overhang_faces(angles, centroids, float(m["bbox_diag"]), limit)
        support[proc] = {"faces": int(len(faces)), "area_mm2": round(float(areas[faces].sum()), 2)}
    sidewalls, draft = draft_sidewalls(angles)
    drafts = {}
    for proc, need in DRAFT_MIN_DEG.items():
        flagged = sidewalls[draft < need]
        drafts[proc] = {"faces": int(len(flagged)), "area_mm2": round(float(areas[flagged].sum()), 2)}
    down_area = float(areas[normals[:, 2] < -0.8].sum()) if len(normals) else 0.0
    out = {
        "id": cid,
        "basis": basis,
        "rotation": [list(row) for row in o.matrix] if not o.is_identity else [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "orientation": None if o.is_identity else o.key,
        "label": o.label,
        "up_in_file": [float(c) for c in o.up],
        "down_in_file": [float(c) for c in -o.up],
        "exact": o.exact,
        "height_mm": round(float(ext[2]), 3),
        "footprint_mm": [round(float(ext[0]), 3), round(float(ext[1]), 3)],
        "on_plate_area_mm2": round(float(areas[on_plate].sum()), 2),
        "support": support,
        "draft": drafts,
        "downward_area_mm2": round(down_area, 2),
        "downward_share_pct": round(down_area / total_area * 100.0, 2) if total_area > 0 else None,
    }
    if extra:
        out.update(extra)
    return out


def _flat_faces(mesh: trimesh.Trimesh, limit: int = 2) -> list[tuple[np.ndarray, float]]:
    """The largest flat faces whose normal isn't a file axis (those are the six sides)."""
    try:
        facets = mesh.facets
        normals = mesh.facets_normal
        areas = mesh.facets_area
    except Exception:
        return []
    if not len(facets):
        return []
    order = sorted(range(len(facets)), key=lambda i: (-round(float(areas[i]), 6), i))
    biggest = float(areas[order[0]])
    total = float(mesh.area) or 1.0
    out: list[tuple[np.ndarray, float]] = []
    for i in order:
        a = float(areas[i])
        if a < 0.5 * biggest or a < 0.01 * total:
            break
        n = np.asarray(normals[i], dtype=float)
        if not np.all(np.isfinite(n)) or np.linalg.norm(n) < 0.5:
            continue
        if _axis_name(_unit(n)) is not None:
            continue
        if any(float(n @ m) > 1 - 1e-6 for m, _ in out):
            continue
        out.append((n / np.linalg.norm(n), a))
        if len(out) >= limit:
            break
    return out


def orientation_options(mesh: trimesh.Trimesh, *, down: list[float] | None = None) -> dict:
    """Compare ways to lay the part down with the check's own rules.

    The six sides of the file's box and up to two of its largest flat faces
    that aren't on a file axis, plus ``down`` when given (a face picked in the
    3D view). For each: the area and faces the overhang rule marks for support
    per printing process, the wall area without draft per molding process (the
    tool opening along the placed +Z), the height and footprint. Deterministic:
    the same mesh always gives the same list and the same best choice.
    """
    from src.analysis.context import _max_analysis_faces, _maybe_decimate

    bounded, decimation = _maybe_decimate(mesh)
    total_area = float(np.asarray(bounded.area_faces, dtype=np.float64).sum())
    cands = [_candidate(cid, "side", rotation_down(d), bounded, total_area) for cid, d in _SIDES]
    for i, (n, a) in enumerate(_flat_faces(bounded), start=1):
        cands.append(_candidate(f"face-{i}", "flat_face", rotation_down(n), bounded, total_area,
                                {"face_area_mm2": round(a, 2)}))
    if down is not None:
        d = _unit(down)
        cands.append(_candidate("picked", "picked", rotation_down(d), bounded, total_area))

    order = {c["id"]: i for i, c in enumerate(cands)}
    best: dict[str, str] = {}
    for proc in OVERHANG_LIMIT_DEG:
        pick = min(cands, key=lambda c: (c["support"][proc]["area_mm2"], round(c["height_mm"], 3),
                                         -c["on_plate_area_mm2"], order[c["id"]]))
        best[proc] = pick["id"]
    for proc in DRAFT_MIN_DEG:
        pick = min(cands, key=lambda c: (c["draft"][proc]["area_mm2"], order[c["id"]]))
        best[proc] = pick["id"]
    return {
        "faces": int(len(mesh.faces)),
        "analysed_faces": int(len(bounded.faces)),
        "decimated": bool(decimation and decimation.get("succeeded")),
        "max_analysis_faces": _max_analysis_faces(),
        "surface_area_mm2": round(total_area, 2),
        "rules": {
            **{p: {"overhang_deg": v} for p, v in OVERHANG_LIMIT_DEG.items()},
            **{p: {"draft_deg": v} for p, v in DRAFT_MIN_DEG.items()},
        },
        "candidates": cands,
        "best": best,
        "ranking": {
            "printing": "Least area needing support, then the lowest height, then the most area on the plate.",
            "molding": "Least wall area without the draft the process needs.",
        },
        "limits": [
            "Prices are the same in every orientation: the cost model prices a print at the lowest "
            "build height the part can take and doesn't price support material.",
            "Undercuts depend on the opening direction too; they are found by re-checking in that orientation, "
            "not compared here.",
            "Support area is the area of the faces the check's overhang rule marks, not the volume of support material.",
        ],
    }

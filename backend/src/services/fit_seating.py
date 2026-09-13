"""Bounded, evidence-reporting two-part seating hypotheses.

Automatic seating is advisory and refuses ambiguity. Shared-frame is always the
fallback because two exports from one CAD assembly already carry exact placement.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh
from scipy.spatial._ckdtree import cKDTree


@dataclass(frozen=True)
class SeatingCandidate:
    method: str
    transform: np.ndarray
    rmse_mm: float
    sample_count: int


def _points(mesh: trimesh.Trimesh, limit: int = 4000) -> np.ndarray:
    vertices = np.asarray(mesh.vertices, dtype=float)
    if len(vertices) <= limit:
        return vertices
    return vertices[np.linspace(0, len(vertices) - 1, limit, dtype=np.int64)]


def _rigid_fit(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    src_center = source.mean(axis=0)
    dst_center = target.mean(axis=0)
    h = (source - src_center).T @ (target - dst_center)
    u, _s, vt = np.linalg.svd(h)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1] *= -1
        rotation = vt.T @ u.T
    transform = np.eye(4)
    transform[:3, :3] = rotation
    transform[:3, 3] = dst_center - rotation @ src_center
    return transform


def _apply(points: np.ndarray, transform: np.ndarray) -> np.ndarray:
    return points @ transform[:3, :3].T + transform[:3, 3]


def _icp(source: np.ndarray, target: np.ndarray, initial: np.ndarray, iterations: int = 20) -> tuple[np.ndarray, float]:
    transform = np.asarray(initial, dtype=float).copy()
    tree = cKDTree(target)
    for _ in range(iterations):
        moved = _apply(source, transform)
        distance, index = tree.query(moved, k=1)
        # Trim the worst 20%; outliers from non-mating surfaces must not steer fit.
        keep = distance <= np.quantile(distance, 0.8)
        delta = _rigid_fit(moved[keep], target[index[keep]])
        transform = delta @ transform
        if np.linalg.norm(delta - np.eye(4)) < 1e-7:
            break
    final, _ = tree.query(_apply(source, transform), k=1)
    return transform, float(np.sqrt(np.mean(np.square(final))))


def _translation(vector: np.ndarray) -> np.ndarray:
    out = np.eye(4)
    out[:3, 3] = vector
    return out


def _initial_hypotheses(a: trimesh.Trimesh, b: trimesh.Trimesh) -> list[tuple[str, np.ndarray]]:
    """Shared frame, centroid ICP, and axis-aligned planar-face mate hypotheses."""
    a_bounds = np.asarray(a.bounds, dtype=float)
    b_bounds = np.asarray(b.bounds, dtype=float)
    a_center = a_bounds.mean(axis=0)
    b_center = b_bounds.mean(axis=0)
    out: list[tuple[str, np.ndarray]] = [("shared_frame_icp", np.eye(4))]
    out.append(("centroid_icp", _translation(a_center - b_center)))
    for axis, name in enumerate("xyz"):
        for a_side, b_side, suffix in ((1, 0, "positive"), (0, 1, "negative")):
            shift = a_center - b_center
            shift[axis] = a_bounds[a_side, axis] - b_bounds[b_side, axis]
            out.append((f"planar_face_{name}_{suffix}_icp", _translation(shift)))
    return out


def _same_transform(a: np.ndarray, b: np.ndarray) -> bool:
    return bool(np.allclose(a, b, atol=1e-4, rtol=0))


def propose_auto_seating(a: trimesh.Trimesh, b: trimesh.Trimesh) -> dict[str, Any]:
    """Return a transform only when bounded ICP produces a clear, low residual fit."""
    target = _points(a)
    source = _points(b)
    candidates: list[SeatingCandidate] = []
    for method, initial in _initial_hypotheses(a, b):
        transform, rmse = _icp(source, target, initial)
        if any(_same_transform(transform, prior.transform) for prior in candidates):
            continue
        candidates.append(SeatingCandidate(method, transform, rmse, len(source)))
    candidates.sort(key=lambda candidate: candidate.rmse_mm)
    best = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    diag = max(float(np.linalg.norm(a.extents)), float(np.linalg.norm(b.extents)), 1e-9)
    low_residual = best.rmse_mm <= max(0.05, diag * 0.01)
    separated = second is None or best.rmse_mm <= second.rmse_mm * 0.9
    accepted = bool(low_residual and separated)
    reason = (
        "clear low-residual ICP refinement" if accepted
        else "auto-seating was ambiguous or high-residual; shared frame retained"
    )
    return {
        "accepted": accepted,
        "method": best.method if accepted else "shared_frame_fallback",
        "transform": best.transform.round(9).tolist() if accepted else np.eye(4).tolist(),
        "rmse_mm": round(best.rmse_mm, 6),
        "second_best_rmse_mm": round(second.rmse_mm, 6) if second else None,
        "sample_count": best.sample_count,
        "candidate_count": len(candidates),
        "reason": reason,
        "manual_nudge_available": True,
    }


def apply_seating(mesh: trimesh.Trimesh, transform: list[list[float]]) -> trimesh.Trimesh:
    out = mesh.copy()
    matrix = np.asarray(transform, dtype=float)
    if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
        raise ValueError("seating transform must be a finite 4x4 matrix")
    out.apply_transform(matrix)
    return out

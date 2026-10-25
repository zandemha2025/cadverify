"""k-NN similarity — "resembles these labeled parts" (spec §6.2).

An ~18-dim, scale-aware geometry feature vector per part, z-score standardized
with a persisted mean/std, compared by Euclidean (L2 == diagonal-Mahalanobis)
distance. A query part's nearest **labeled** neighbours are returned together with
the 2-3 ``shared`` descriptors that explain the match.

Computed in the same engine pass as routing (reuses ``geometry`` + ``ctx`` +
``ctx.features``) so a part is analyzed once.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import trimesh

from src.analysis.context import GeometryContext
from src.analysis.features.base import FeatureKind
from src.analysis.models import GeometryInfo
from src.corpus.paths import FEATURES_NPZ
from src.eval import labels as label_store
from src.eval.engine import geometry_pass

# Ordered names of the 18 feature dimensions (spec §6.2 table).
DIMS: list[str] = [
    "elongation",         # 1  d2/d1
    "flatness",           # 2  d3/d1
    "squareness",         # 3  d3/d2
    "solidity",           # 4  |vol| / hullV
    "compactness",        # 5  A / diag^2
    "rel_wall",           # 6  median_wall / diag
    "log_faces",          # 7  log10(n_faces)
    "log_diag",           # 8  log10(diag)
    "watertight",         # 9  1.0 / 0.0
    "log_bodies",         # 10 log1p(body_count)
    "genus_proxy",        # 11 clip((2 - euler)/2, -5, 5)
    "log_n_holes",        # 12 log1p(#CYLINDER_HOLE)
    "log_n_bosses",       # 13 log1p(#CYLINDER_BOSS)
    "log_n_flats",        # 14 log1p(#FLAT)
    "log_n_curved",       # 15 log1p(#CURVED)
    "flat_area_frac",     # 16 sum(FLAT area)/A
    "curved_area_frac",   # 17 sum(CURVED area)/A
    "largest_flat_frac",  # 18 max(FLAT area)/A
]
N_DIMS = len(DIMS)


def _finite(x: float) -> float:
    """Map non-finite / failed components to 0.0 (never NaN)."""
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return 0.0
    return xf if np.isfinite(xf) else 0.0


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def feature_vector(
    mesh: trimesh.Trimesh,
    geometry: GeometryInfo,
    ctx: GeometryContext,
) -> np.ndarray:
    """Compute the 18-dim feature vector (spec §6.2). Never returns NaN."""
    v = np.zeros(N_DIMS, dtype=np.float64)

    dims = sorted((float(d) for d in geometry.bounding_box.dimensions), reverse=True)
    if len(dims) != 3:
        return v
    d1, d2, d3 = dims  # d1 >= d2 >= d3
    diag = float(np.sqrt(d1 * d1 + d2 * d2 + d3 * d3))

    # Convex-hull volume is robust even when the mesh is not watertight.
    try:
        hull_v = float(mesh.convex_hull.volume)
    except Exception:
        hull_v = 0.0
    A = float(geometry.surface_area)

    wt = np.asarray(ctx.wall_thickness, dtype=np.float64)
    wt = wt[np.isfinite(wt)]
    mw = float(np.median(wt)) if wt.size else 0.0

    # Feature-kind tallies (CYLINDER_HOLE / CYLINDER_BOSS / FLAT / CURVED).
    feats = ctx.features or []
    n_hole = n_boss = n_flat = n_curved = 0
    flat_areas: list[float] = []
    curved_area_sum = 0.0
    for f in feats:
        if f.kind == FeatureKind.CYLINDER_HOLE:
            n_hole += 1
        elif f.kind == FeatureKind.CYLINDER_BOSS:
            n_boss += 1
        elif f.kind == FeatureKind.FLAT:
            n_flat += 1
            if f.area:
                flat_areas.append(float(f.area))
        elif f.kind == FeatureKind.CURVED:
            n_curved += 1
            if f.area:
                curved_area_sum += float(f.area)

    n_faces = int(geometry.face_count)
    body_count = len(ctx.bodies) if ctx.bodies else 1

    v[0] = _finite(d2 / d1) if d1 > 0 else 0.0
    v[1] = _finite(d3 / d1) if d1 > 0 else 0.0
    v[2] = _finite(d3 / d2) if d2 > 0 else 0.0
    v[3] = _clip(_finite(abs(float(geometry.volume)) / hull_v), 0.0, 1.0) if hull_v > 1e-9 else 0.0
    v[4] = _finite(A / (diag * diag)) if diag > 0 else 0.0
    v[5] = _clip(_finite(mw / diag), 0.0, 1.0) if diag > 0 else 0.0
    v[6] = _finite(np.log10(max(n_faces, 1)))
    v[7] = _finite(np.log10(max(diag, 1e-3)))
    v[8] = 1.0 if bool(geometry.is_watertight) else 0.0
    v[9] = _finite(np.log1p(max(body_count, 0)))
    v[10] = _clip(_finite((2 - float(geometry.euler_number)) / 2.0), -5.0, 5.0)
    v[11] = _finite(np.log1p(n_hole))
    v[12] = _finite(np.log1p(n_boss))
    v[13] = _finite(np.log1p(n_flat))
    v[14] = _finite(np.log1p(n_curved))
    v[15] = _clip(_finite(sum(flat_areas) / A), 0.0, 1.0) if A > 0 else 0.0
    v[16] = _clip(_finite(curved_area_sum / A), 0.0, 1.0) if A > 0 else 0.0
    v[17] = _clip(_finite(max(flat_areas) / A), 0.0, 1.0) if (A > 0 and flat_areas) else 0.0

    # Final guard: scrub any residual non-finite value.
    v[~np.isfinite(v)] = 0.0
    return v


def vector_for_mesh(mesh: trimesh.Trimesh) -> np.ndarray:
    """Run the geometry pass and compute the feature vector for a loose mesh."""
    gp = geometry_pass(mesh)
    return feature_vector(gp.mesh, gp.geometry, gp.ctx)


# ──────────────────────────────────────────────────────────────
# Matrix build / persist
# ──────────────────────────────────────────────────────────────
@dataclass
class FeatureStore:
    part_ids: np.ndarray  # (N,) str
    X: np.ndarray         # (N, 18) raw
    mean: np.ndarray      # (18,)
    std: np.ndarray       # (18,)  already +1e-9
    dims: list[str]

    def index_of(self, part_id: str) -> Optional[int]:
        hits = np.where(self.part_ids == part_id)[0]
        return int(hits[0]) if len(hits) else None


def _store_from_rows(part_ids: list[str], rows: np.ndarray) -> FeatureStore:
    mean = rows.mean(axis=0) if rows.shape[0] else np.zeros(N_DIMS)
    std = (rows.std(axis=0) if rows.shape[0] else np.zeros(N_DIMS)) + 1e-9
    return FeatureStore(
        part_ids=np.array(part_ids, dtype=object),
        X=rows,
        mean=mean,
        std=std,
        dims=list(DIMS),
    )


def build_feature_matrix(
    part_ids: Optional[Sequence[str]] = None,
    manifest: Optional[dict[str, dict]] = None,
    progress: bool = False,
    precomputed: Optional[dict[str, np.ndarray]] = None,
    on_checkpoint: Optional["object"] = None,
    checkpoint_every: int = 40,
) -> FeatureStore:
    """Build the raw feature matrix over the given parts (default: all corpus).

    One geometry pass per part. Parts that fail to load contribute a zero row and
    a warning to stderr (never fabricated geometry).

    Resumable: ``precomputed`` (``{part_id: vector}``) rows are reused without
    recomputing; they are ordered first so an ``on_checkpoint(part_ids, rows)``
    callback (invoked every ``checkpoint_every`` newly-computed parts) only ever
    sees fully-valid rows — a kill mid-build never loses completed work.
    """
    if manifest is None:
        manifest = label_store.load_manifest()
    if part_ids is None:
        part_ids = list(manifest.keys())
    precomputed = precomputed or {}

    # Order: already-computed first, then the to-do parts.
    done = [p for p in part_ids if p in precomputed]
    todo = [p for p in part_ids if p not in precomputed]
    ordered = done + todo

    rows = np.zeros((len(ordered), N_DIMS), dtype=np.float64)
    for i, pid in enumerate(done):
        rows[i] = precomputed[pid]

    base = len(done)
    n_done = 0
    for j, pid in enumerate(todo):
        i = base + j
        path = label_store.mesh_path(pid, manifest)
        try:
            mesh = trimesh.load(path, force="mesh")
            rows[i] = vector_for_mesh(mesh)
        except Exception as exc:  # pragma: no cover - corrupt mesh on disk
            print(f"WARN: feature build failed for {pid}: {exc}", file=sys.stderr)
        n_done += 1
        if progress and n_done % 20 == 0:
            print(f"  features {base + n_done}/{len(ordered)}", file=sys.stderr)
        if on_checkpoint is not None and n_done % checkpoint_every == 0:
            on_checkpoint(ordered[: i + 1], rows[: i + 1].copy())

    return _store_from_rows(ordered, rows)


def save_features(store: FeatureStore, path: Optional[Path] = None) -> None:
    """Persist the feature store atomically (temp file + rename)."""
    path = Path(path if path is not None else FEATURES_NPZ)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    np.savez(
        tmp,
        part_ids=store.part_ids.astype(str),
        X=store.X,
        mean=store.mean,
        std=store.std,
        dims=np.array(store.dims, dtype=object),
    )
    # np.savez appends .npz to the filename; normalize then atomically replace.
    written = tmp if tmp.exists() else tmp.with_suffix(tmp.suffix + ".npz")
    import os

    os.replace(written, path)


def load_features(path: Optional[Path] = None) -> FeatureStore:
    path = path if path is not None else FEATURES_NPZ
    data = np.load(path, allow_pickle=True)
    return FeatureStore(
        part_ids=np.array([str(p) for p in data["part_ids"]], dtype=object),
        X=np.asarray(data["X"], dtype=np.float64),
        mean=np.asarray(data["mean"], dtype=np.float64),
        std=np.asarray(data["std"], dtype=np.float64),
        dims=[str(d) for d in data["dims"]],
    )


# ──────────────────────────────────────────────────────────────
# k-NN query
# ──────────────────────────────────────────────────────────────
@dataclass
class Neighbor:
    part_id: str
    label: str
    distance: float
    dataset: Optional[str]
    shared: list[str]


def _zscore(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return (x - mean) / std


def knn(
    query_vec: np.ndarray,
    store: FeatureStore,
    candidate_labels: dict[str, str],
    k: int = 8,
    manifest: Optional[dict[str, dict]] = None,
    exclude_part_id: Optional[str] = None,
) -> list[Neighbor]:
    """Return the ``k`` nearest **labeled** parts to ``query_vec``.

    ``candidate_labels`` is ``{part_id: label}`` — only these parts are eligible
    neighbours (the explainable "resembles these *labeled* parts" evidence).
    """
    if store.X.shape[0] == 0:
        return []
    qz = _zscore(np.asarray(query_vec, dtype=np.float64), store.mean, store.std)
    Xz = _zscore(store.X, store.mean, store.std)

    results: list[Neighbor] = []
    for pid, label in candidate_labels.items():
        if exclude_part_id is not None and pid == exclude_part_id:
            continue
        idx = store.index_of(pid)
        if idx is None:
            continue
        nz = Xz[idx]
        dist = float(np.linalg.norm(qz - nz))
        # `shared` = dims where query and neighbour are closest (smallest |z-diff|).
        diffs = np.abs(qz - nz)
        order = np.argsort(diffs)[:3]
        shared = [store.dims[j] for j in order]
        dataset = None
        if manifest and pid in manifest:
            dataset = manifest[pid].get("dataset")
        results.append(
            Neighbor(part_id=pid, label=label, distance=dist, dataset=dataset, shared=shared)
        )
    results.sort(key=lambda n: n.distance)
    return results[:k]


# ──────────────────────────────────────────────────────────────
# CLI: python -m src.eval.similarity --part <id> --k 8   |  --stl <path>
# ──────────────────────────────────────────────────────────────
def _resolve_query_vector(
    args: argparse.Namespace,
    store: FeatureStore,
    manifest: dict[str, dict],
) -> tuple[str, np.ndarray, Optional[str]]:
    """Return (query_label, query_vec, exclude_part_id)."""
    if args.part:
        idx = store.index_of(args.part)
        if idx is not None:
            return args.part, store.X[idx], args.part
        # Not in the prebuilt matrix — compute on the fly.
        path = label_store.mesh_path(args.part, manifest)
        mesh = trimesh.load(path, force="mesh")
        return args.part, vector_for_mesh(mesh), args.part
    # --stl path: hash to see if it's already in the corpus, else compute fresh.
    raw = Path(args.stl).read_bytes()
    pid = hashlib.sha256(raw).hexdigest()
    idx = store.index_of(pid)
    if idx is not None:
        return f"{args.stl} (==corpus {pid[:12]})", store.X[idx], pid
    mesh = trimesh.load(Path(args.stl), force="mesh")
    return args.stl, vector_for_mesh(mesh), pid


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="k-NN similarity over the corpus feature matrix")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--part", help="query by an existing corpus part_id")
    src.add_argument("--stl", help="query by a path to an STL file (hashed)")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument(
        "--smoke",
        action="store_true",
        help="use the SMOKE seed labels as the neighbour pool (pipeline exercise only)",
    )
    ap.add_argument("--labeler", default=None, help="restrict neighbour pool to one labeler")
    args = ap.parse_args(argv)

    if not Path(FEATURES_NPZ).exists():
        print(
            f"ERROR: {FEATURES_NPZ} not found. Build it first:\n"
            "  python -m src.eval.run --build-features",
            file=sys.stderr,
        )
        return 2
    store = load_features()
    manifest = label_store.load_manifest()
    if args.smoke:
        pool = label_store.smoke_labels()
        pool_note = "SMOKE — synthetic seed labels, NOT human ground truth"
    else:
        pool = label_store.human_labels(labeler=args.labeler)
        pool_note = "human labels"

    q_label, q_vec, exclude = _resolve_query_vector(args, store, manifest)
    neighbors = knn(q_vec, store, pool, k=args.k, manifest=manifest, exclude_part_id=exclude)
    out = {
        "query": q_label,
        "neighbor_pool": pool_note,
        "neighbors": [
            {
                "part_id": n.part_id,
                "label": n.label,
                "distance": round(n.distance, 3),
                "dataset": n.dataset,
                "shared": n.shared,
            }
            for n in neighbors
        ],
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

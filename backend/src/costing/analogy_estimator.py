"""Analogy-to-quote estimator — a GENUINE second ensemble member (Moat P1, §4/§6).

The assumption ensemble (``ensemble.py``) is ONE physics/feature estimator run
under K perturbations — an assumption *spread*, not a second opinion. This module
adds a truly INDEPENDENT estimator: a **k-nearest-neighbour over REAL ground-truth
quotes** with similar geometry, for the same process. It answers a different
question ("what did this shop actually charge for parts LIKE this one?") from a
different data source (returned quotes, not the rate card), so combining it with
the physics point by inverse-variance/BLUE can only tighten the band (§6).

Honesty rails (identical spirit to ``groundtruth.py`` / ``groundtruth_service.py``):

  * **Real quotes only.** Stand-in / synthetic records (``stand_in=True``) are
    NEVER used — they can shape a spread but can never earn a served number. The
    neighbour pool is filtered to ``stand_in=False`` records of the SAME process.
  * **Abstain, never fabricate.** With fewer than ``min_real`` real neighbours (or
    no query geometry), ``analogy_estimate`` returns ``None``. The caller then
    falls back to the physics-only assumption band, byte-identically.
  * **Not "validated".** A real-analogy member contributing to the band does NOT
    set ``validated`` — that still requires the MEASURED residual path
    (``ResidualModel`` / held-out residuals). Analogy is a real-data *prior*, not
    a measured accuracy claim.

Distance metric (documented, deterministic — no wall-clock/global randomness):
    Weighted Euclidean distance in a robust, scale-normalised LOG-feature space
    over the MEASURED geometry cost-drivers the engine already extracts
    (``GeoDrivers``): volume, surface area, max bounding-box extent, face count —
    plus log-quantity (so quotes at a similar lot size are preferred, since the
    learning curve moves unit cost). Log because these drivers span orders of
    magnitude; each dimension is divided by the candidate pool's population std
    (a robust, pool-relative scale) so no single large-magnitude driver dominates.
    A dimension with zero spread in the pool is ignored. The pool-relative scaling
    is computed from the (query + real same-process neighbours) set only, so the
    result is a pure deterministic function of the inputs.

Purity: no engine calls, no I/O, no randomness. Unit-testable with in-memory
record lists whose parts carry a ``geometry_features`` mapping (or via an explicit
``features_by_part`` map).
"""

from __future__ import annotations

import math
from typing import Callable, NamedTuple, Optional, Sequence

# The MEASURED geometry drivers we match on (names mirror ``GeoDrivers`` /
# ``drivers.py``). Every one is extracted from the CAD, never assumed.
FEATURE_KEYS = ("volume_cm3", "surface_area_cm2", "max_bbox_mm", "face_count")

# Below this many REAL same-process neighbours with usable geometry the analogy
# member ABSTAINS (returns None). Aligned with ``groundtruth.MIN_RESIDUALS`` (3),
# the per-process floor below which we will not advertise an empirical band: a
# k-NN over quotes needs at least a few analogous real parts to form a spread.
DEFAULT_MIN_REAL_NEIGHBORS = 3

# Default neighbourhood size. Fewer real neighbours than this simply uses all of
# them (down to the ``min_real`` floor).
DEFAULT_K = 5

# The analogy member never claims impossible precision from a handful of quotes:
# its empirical variance is floored at (MIN_REL_STD × value)². k-NN over real
# quotes is a strong prior, not an oracle.
MIN_REL_STD = 0.05

# Weight given to the log-quantity dimension relative to a geometry dimension.
# < 1 so geometry similarity dominates but lot size still nudges neighbour choice.
_QTY_WEIGHT = 0.5

ANALOGY_PROVENANCE = "REAL ground-truth k-NN (analogy-to-quote)"


class AnalogyEstimate(NamedTuple):
    """One analogy member's output: a distribution (value + variance), never a
    bare point. ``value_usd`` is the distance-weighted mean neighbour unit cost;
    ``variance_usd2`` is the (floored) weighted neighbour-spread variance;
    ``n_used`` is how many REAL neighbours contributed."""

    value_usd: float
    variance_usd2: float
    n_used: int


def _features_for(record, features_by_part: Optional[dict]) -> Optional[dict]:
    """Resolve a record's geometry features. Prefers an explicit
    ``features_by_part[part_id]`` map; else an attached ``geometry_features`` attr
    on the record. Returns None when no usable features are available (that record
    simply cannot be a neighbour)."""
    if features_by_part is not None:
        gf = features_by_part.get(getattr(record, "part_id", None))
        if isinstance(gf, dict):
            return gf
    gf = getattr(record, "geometry_features", None)
    if isinstance(gf, dict):
        return gf
    return None


def _vector(features: dict, quantity: float) -> Optional[list]:
    """Log-feature vector [log(volume), log(area), log(max_bbox), log(faces),
    log(qty)] — or None if any required driver is missing / non-positive (a part
    with no measurable geometry cannot be matched honestly)."""
    vec = []
    for key in FEATURE_KEYS:
        v = features.get(key)
        if v is None:
            return None
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        if v <= 0.0:
            return None
        vec.append(math.log(v))
    q = float(quantity) if quantity and quantity > 0 else 1.0
    vec.append(math.log(q))
    return vec


def _pstd(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mu = sum(values) / n
    return (sum((x - mu) ** 2 for x in values) / n) ** 0.5


def analogy_estimate(
    process: str,
    quantity: int,
    geometry_features: Optional[dict],
    records: Sequence,
    *,
    k: int = DEFAULT_K,
    min_real: int = DEFAULT_MIN_REAL_NEIGHBORS,
    features_by_part: Optional[dict] = None,
    feature_fn: Optional[Callable[[object], Optional[dict]]] = None,
) -> Optional[AnalogyEstimate]:
    """k-NN-over-real-quotes analogy estimate for one (process, quantity).

    Returns ``AnalogyEstimate(value_usd, variance_usd2, n_used)`` — or ``None``
    (ABSTAIN) when there is insufficient real ground truth to answer honestly:
    no query geometry, or fewer than ``min_real`` REAL (``stand_in=False``)
    same-process neighbours that carry usable geometry.

    The value is the distance-weighted mean of the neighbours' actual unit costs;
    the variance is the (floored) weighted neighbour-spread variance. Deterministic
    in its inputs (no randomness, no wall-clock).
    """
    if geometry_features is None:
        return None
    query = _vector(geometry_features, quantity)
    if query is None:
        return None

    resolve = feature_fn or (lambda r: _features_for(r, features_by_part))

    # Candidate pool: REAL, same-process records that carry usable geometry.
    pool = []  # (record, log-feature-vector, actual_unit_cost)
    for r in records:
        if getattr(r, "stand_in", True):
            continue                                  # stand-in never counts
        if getattr(r, "process", None) != process:
            continue
        feats = resolve(r)
        if not isinstance(feats, dict):
            continue
        vec = _vector(feats, getattr(r, "quantity", quantity))
        if vec is None:
            continue
        cost = getattr(r, "actual_unit_cost_usd", None)
        try:
            cost = float(cost)
        except (TypeError, ValueError):
            continue
        if cost <= 0.0:
            continue
        pool.append((r, vec, cost))

    if len(pool) < max(1, int(min_real)):
        return None                                    # ABSTAIN — too little real data

    dim = len(query)
    # Pool-relative robust scale per dimension (population std over query+pool).
    scales = []
    for d in range(dim):
        col = [query[d]] + [vec[d] for _r, vec, _c in pool]
        s = _pstd(col)
        scales.append(s if s > 1e-12 else 0.0)        # zero-spread dim => ignored

    weights_dim = [1.0] * (dim - 1) + [_QTY_WEIGHT]

    def _distance(vec):
        acc = 0.0
        for d in range(dim):
            if scales[d] == 0.0:
                continue
            z = (vec[d] - query[d]) / scales[d]
            acc += weights_dim[d] * z * z
        return math.sqrt(acc)

    scored = []
    for idx, (r, vec, cost) in enumerate(pool):
        d = _distance(vec)
        # Deterministic ordering: nearest first, then stable by part_id then index.
        scored.append((d, str(getattr(r, "part_id", "")), idx, cost))
    scored.sort(key=lambda t: (t[0], t[1], t[2]))

    kk = max(int(min_real), min(int(k) if k and k > 0 else len(scored), len(scored)))
    neighbours = scored[:kk]
    if len(neighbours) < int(min_real):
        return None

    # Inverse-distance weights (an exact-match neighbour dominates but stays finite).
    eps = 1e-9
    costs = [c for _d, _pid, _i, c in neighbours]
    inv = [1.0 / (d * d + eps) for d, _pid, _i, _c in neighbours]
    w_sum = sum(inv)
    if w_sum <= 0.0:
        return None
    value = sum(w * c for w, c in zip(inv, costs)) / w_sum
    # Weighted (population) neighbour-spread variance — the empirical uncertainty.
    var = sum(w * (c - value) ** 2 for w, c in zip(inv, costs)) / w_sum
    floor = (MIN_REL_STD * value) ** 2
    var = max(var, floor)
    return AnalogyEstimate(value_usd=float(value), variance_usd2=float(var),
                           n_used=len(neighbours))

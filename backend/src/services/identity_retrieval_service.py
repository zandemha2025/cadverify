"""Identity-retrieval grounding engine — org-scoped, zero-egress (identity Slice 1).

Geometry alone can never say "this is a Camry LE door handle" — that identity
lives in the CUSTOMER's world. This engine GROUNDS a new part's identity by
RETRIEVING the org's own closest prior parts (geometry k-NN over their corpus)
and, when the customer declared a name/part-number on those neighbours, blending a
lexical name-match on top. The output is ALWAYS a provenance-tagged, confidence-
scored SUGGESTION to confirm — never an asserted fact. It retrieves; it never
hallucinates an identity.

Honesty rails (the founder's north star — real where we can be, honest where we
can't):

  * **Empty corpus → honest empty.** Before the org has analyzed anything, there is
    nothing to retrieve. We return ``matches=[]``, ``grounded=False`` and a reason
    that says to fall back to the standard catalog + file metadata — we NEVER
    fabricate an identity from an empty corpus.
  * **A retrieved identity is a SUGGESTION.** Every match carries a
    ``combined_confidence`` in [0,1], a ``confidence_bucket`` (HIGH/MEDIUM/LOW), and
    the provenance string ``RETRIEVED (org corpus: geometry k-NN + name match)``.
    ``grounded`` is True ONLY when the top match clears the MEDIUM bar. Below it we
    claim NO identity.
  * **geometry_similarity is a documented PROXY, not a probability.** It is a
    monotonic mapping of a z-scored L2 distance; a small distance means "close in
    the org's own feature space", nothing more. We say so in the notes.
  * **Cross-org isolation.** The engine only ever reads ``org_id = caller`` (via
    ``part_signature_service.list_signatures``). It can never return another org's
    parts.

Determinism / purity: the scoring core (distance→similarity, name similarity, the
blend + buckets) is pure and unit-testable without HTTP or a network. The only I/O
is the org-scoped corpus read. Zero egress.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np
import trimesh
from sqlalchemy.ext.asyncio import AsyncSession

from src.eval import similarity
from src.services import part_signature_service as sigsvc

# ---------------------------------------------------------------------------
# SHAPE-FAITHFUL identity distance — down-weight re-tessellation-sensitive dims.
#
# The 18-dim signature (``similarity.DIMS``) mixes two very different kinds of
# feature. Some describe the part's actual 3-D SHAPE, derived from global geometry
# (bounding-box ratios, hull-volume solidity, area/diag² compactness, wall/diag,
# absolute log-scale) — these are stable under a re-mesh. The rest are artifacts of
# the specific TESSELLATION and of the FLAT/CURVED/CYLINDER feature classifier
# (face count, watertight flag, body/genus topology, hole/boss/flat/curved counts
# and their area fractions) — these move when the SAME part is re-meshed even though
# its shape is unchanged.
#
# We proved this on the flagship asset: ``bracket_A`` and its genuine revision
# ``bracket_A_rev`` (1 % rescale + sub-0.1 mm jitter) have IDENTICAL shape
# descriptors, yet the classifier reports 38 vs 4 FLAT facets and flat_area_frac
# 1.00 vs 0.40 — a huge move in feature space for zero shape change. Z-scoring then
# magnifies it (a low-spread feature dim explodes). So for IDENTITY matching only
# (NOT the eval-harness vector in ``similarity.py``) we weight the distance to the
# re-mesh-ROBUST shape/scale descriptors and DROP the tessellation/classifier dims.
#
# Weight per dim (index → similarity.DIMS name). 1.0 = keep, 0.0 = drop:
#   0  elongation        1.0  bbox ratio d2/d1        — shape, re-mesh robust
#   1  flatness          1.0  bbox ratio d3/d1        — shape, re-mesh robust
#   2  squareness        1.0  bbox ratio d3/d2        — shape, re-mesh robust
#   3  solidity          1.0  |vol|/hullV             — shape, re-mesh robust
#   4  compactness       1.0  A/diag²                 — shape, re-mesh robust
#   5  rel_wall          1.0  median_wall/diag        — shape, re-mesh robust
#   6  log_faces         0.0  log10(n_faces)          — PURE tessellation density
#   7  log_diag          1.0  log10(diag)             — absolute scale, re-mesh
#                                                        robust; a genuine revision's
#                                                        ≤few-% rescale barely moves
#                                                        it, but it keeps a tiny part
#                                                        from matching a huge one
#   8  watertight        0.0  1/0                      — flips on a re-mesh
#   9  log_bodies        0.0  log1p(body_count)       — connected-component artifact
#   10 genus_proxy       0.0  (2-euler)/2             — topology, re-mesh sensitive
#   11 log_n_holes       0.0  classifier count        — feature-detection sensitive
#   12 log_n_bosses      0.0  classifier count        — feature-detection sensitive
#   13 log_n_flats       0.0  classifier count        — the worst mover (38↔4)
#   14 log_n_curved      0.0  classifier count        — feature-detection sensitive
#   15 flat_area_frac    0.0  classifier area frac    — moved 1.00↔0.40 on the rev
#   16 curved_area_frac  0.0  classifier area frac    — feature-detection sensitive
#   17 largest_flat_frac 0.0  classifier area frac    — feature-detection sensitive
#
# The kept 7 dims are exactly the scale-invariant SHAPE descriptors plus absolute
# log-scale — everything computed from global geometry, nothing from the classifier.
# ---------------------------------------------------------------------------
IDENTITY_DIM_WEIGHTS: list[float] = [
    1.0, 1.0, 1.0, 1.0, 1.0, 1.0,  # 0-5  shape descriptors
    0.0,                            # 6    log_faces (tessellation density)
    1.0,                            # 7    log_diag (absolute scale, robust)
    0.0, 0.0, 0.0,                  # 8-10 watertight / bodies / genus (topology)
    0.0, 0.0, 0.0, 0.0,             # 11-14 hole/boss/flat/curved counts
    0.0, 0.0, 0.0,                  # 15-17 area fractions (classifier-derived)
]

# ---------------------------------------------------------------------------
# Confidence calibration — documented, honest, recalibrated against REAL pairs on
# the shape-faithful distance above (measured in a realistic 7-part org corpus):
#
#   bracket_A ↔ bracket_A_rev (genuine revision, same part) : dist ≈ 0.505
#   bracket_A ↔ torus_unrelated (genuinely different shape)  : dist ≈ 41.0
#   plate ↔ l-bracket (two distinct-but-similar flat slabs)  : dist ≈ 0.73
#   bracket_A ↔ disc (moderately different)                  : dist ≈ 4.10
#
# geometry_similarity(distance): the shape-faithful z-scored L2 distance d ≥ 0 is
# mapped to a similarity in (0,1] by an exponential decay
#     geometry_similarity = exp(-d / GEOM_DECAY)
# MONOTONIC (nearer ⇒ higher), 1.0 only at an exact match (d=0), a documented PROXY
# — never a probability. GEOM_DECAY = 2.0 is recalibrated for the shape-faithful
# metric so the genuine revision at d≈0.505 lands sim≈0.78 (a clean MEDIUM, grounded)
# while the torus at d≈41 decays to ≈0 (LOW, never suggested).
# ---------------------------------------------------------------------------
GEOM_DECAY = 2.0

# A geometry distance at/under this is treated as a near-DUPLICATE — close enough
# that geometry ALONE can carry a HIGH bucket even without a name agreeing. Set
# BELOW the measured genuine-revision distance (≈0.505) so a revision alone reads
# MEDIUM, never HIGH — HIGH stays reserved for a near-EXACT re-verify (d→0) or real
# name agreement. (Recalibrated from 0.60 for the shape-faithful metric.)
GEOM_NEAR_DUPLICATE_DIST = 0.35

# Lever 2 — the honest LOW-confidence "closest in your library" floor. When the top
# match is real but BELOW the MEDIUM auto-suggest bar, we surface it as a distinct,
# clearly-labeled low-confidence candidate ONLY when it is BOTH non-trivial (its
# geometry proxy clears LOW_SUGGEST_SIM — well above the torus's ≈0) AND clearly
# separated from the runner-up (its proxy beats the 2nd-best by LOW_SUGGEST_MARGIN,
# so an ambiguous crowd of equidistant parts yields NO single suggestion). Below the
# floor (the torus) → nothing. Never auto-asserted — always a user-confirmed hint.
LOW_SUGGEST_SIM = 0.35
LOW_SUGGEST_MARGIN = 0.08

# Blend: combined = GEOM_WEIGHT*geometry + (1-GEOM_WEIGHT)*name, BUT only when a
# name hint AND a declared name exist to compare. Geometry is the anchor (it is
# always measured); the name is corroboration when present. When there is no name
# to compare on EITHER side, the combined score is the geometry proxy alone (we
# never invent name agreement, and never penalise a part for a missing name).
GEOM_WEIGHT = 0.65

# Bucket thresholds on the combined confidence. HIGH additionally requires that
# geometry is genuinely close (see retrieve_identity) — a high blended score driven
# by name alone over mediocre geometry is never HIGH.
HIGH_CONFIDENCE = 0.82
MEDIUM_CONFIDENCE = 0.55

PROVENANCE = "RETRIEVED (org corpus: geometry k-NN + name match)"

_GEOM_PROXY_NOTE = (
    "geometry_similarity is a documented proxy (exp(-z_scored_L2 / "
    f"{GEOM_DECAY})), monotonic in geometric closeness — NOT a probability."
)
_SUGGESTION_NOTE = (
    "a retrieved SUGGESTION to confirm, not a verified identity; retrieval can be "
    "wrong — check before trusting."
)
_EMPTY_REASON = (
    "no org corpus yet — falls back to standard-catalog + file metadata "
    "(never a fabricated identity)"
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class IdentityMatch:
    """One ranked retrieved candidate — always a SUGGESTION, never an assertion."""

    mesh_hash: str
    declared_part_id: Optional[str]
    declared_name: Optional[str]
    program: Optional[str]
    geometry_similarity: float
    name_similarity: Optional[float]
    combined_confidence: float
    confidence_bucket: str
    geometry_distance: float
    provenance: str = PROVENANCE

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class IdentityMatchResult:
    """The retrieval-grounding answer for one query part.

    ``grounded`` is True ONLY when the top match clears the MEDIUM bar — otherwise
    NO identity is claimed (honest empty / low). ``matches`` is ranked best-first.
    """

    grounded: bool
    matches: list[IdentityMatch] = field(default_factory=list)
    reason: Optional[str] = None
    caveats: list[str] = field(default_factory=list)
    provenance: Optional[str] = None
    corpus_size: int = 0
    # Lever 2 — an HONEST low-confidence suggestion. Set ONLY when the result is NOT
    # grounded (top match below the MEDIUM bar) yet the closest prior part is clearly
    # above noise AND well-separated from the runner-up (see LOW_SUGGEST_* floors).
    # It is the SAME IdentityMatch object, surfaced as a distinct "closest in your
    # library — low confidence, is this it?" candidate the user confirms; NEVER
    # auto-asserted. None whenever grounded (the confident card carries it) or when
    # nothing clears the floor (e.g. an unrelated part like the torus).
    closest_unconfirmed: Optional[IdentityMatch] = None

    def to_dict(self) -> dict:
        return {
            "grounded": self.grounded,
            "matches": [m.to_dict() for m in self.matches],
            "reason": self.reason,
            "caveats": self.caveats,
            "provenance": self.provenance,
            "corpus_size": self.corpus_size,
            "closest_unconfirmed": (
                self.closest_unconfirmed.to_dict()
                if self.closest_unconfirmed is not None
                else None
            ),
        }


# ---------------------------------------------------------------------------
# Pure scoring core (no DB, no network — unit-testable directly)
# ---------------------------------------------------------------------------


def geometry_similarity(distance: float) -> float:
    """Map a z-scored L2 distance (≥0) to a similarity proxy in (0,1].

    MONOTONIC decreasing: exp(-d / GEOM_DECAY). 1.0 at an exact match (d=0),
    decaying toward 0 as the shapes separate in the org's own feature space. A
    documented PROXY for geometric closeness — explicitly NOT a probability.
    """
    d = max(0.0, float(distance))
    return float(math.exp(-d / GEOM_DECAY))


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _normalize_tokens(text: Optional[str]) -> set[str]:
    """Lower-case, split on non-alphanumeric, drop empties → a token set. Pure,
    deterministic, no external model."""
    if not text:
        return set()
    return set(_TOKEN_RE.findall(str(text).lower()))


def name_similarity(query_name: Optional[str], candidate_name: Optional[str]) -> Optional[float]:
    """Lexical similarity in [0,1] between two names, or ``None`` when either side
    has no comparable name (an honest "not applicable", never 0 by default).

    A documented, deterministic blend of:
      * Jaccard token overlap (|A∩B| / |A∪B|) — order-independent word agreement;
      * a containment bonus — when one name's tokens are a subset of the other's
        (e.g. "handle" vs "door handle left"), overlap alone under-counts, so we
        take the max of Jaccard and the smaller-set containment ratio.
    No external model, no network. Returns ``None`` if either token set is empty.
    """
    a = _normalize_tokens(query_name)
    b = _normalize_tokens(candidate_name)
    if not a or not b:
        return None
    inter = len(a & b)
    union = len(a | b)
    jaccard = inter / union if union else 0.0
    containment = inter / min(len(a), len(b)) if inter else 0.0
    return float(max(jaccard, containment))


def combined_confidence(
    geom_sim: float, name_sim: Optional[float]
) -> float:
    """Honest blend of geometry proxy and (optional) name similarity → [0,1].

    * Both present → GEOM_WEIGHT*geometry + (1-GEOM_WEIGHT)*name (geometry anchors,
      the name corroborates).
    * No comparable name on either side → the geometry proxy ALONE (we never invent
      name agreement, and never penalise a part for having no declared name).
    """
    g = max(0.0, min(1.0, float(geom_sim)))
    if name_sim is None:
        return g
    n = max(0.0, min(1.0, float(name_sim)))
    return float(GEOM_WEIGHT * g + (1.0 - GEOM_WEIGHT) * n)


def confidence_bucket(
    combined: float, *, geometry_distance: float, name_sim: Optional[float]
) -> str:
    """Bucket a match HIGH / MEDIUM / LOW with STATED thresholds and an honest
    HIGH gate.

    HIGH requires the combined score to clear ``HIGH_CONFIDENCE`` AND geometry to
    be genuinely close — specifically EITHER a name actually agrees
    (``name_sim`` is not None and ≥ 0.5) OR the geometry is a near-duplicate
    (``geometry_distance`` ≤ ``GEOM_NEAR_DUPLICATE_DIST``). This blocks a
    name-driven high score over mediocre geometry from ever reading HIGH.
    MEDIUM clears ``MEDIUM_CONFIDENCE``; everything else is LOW.
    """
    c = float(combined)
    if c >= HIGH_CONFIDENCE:
        name_agrees = name_sim is not None and name_sim >= 0.5
        near_dup = geometry_distance <= GEOM_NEAR_DUPLICATE_DIST
        if name_agrees or near_dup:
            return "HIGH"
        return "MEDIUM"
    if c >= MEDIUM_CONFIDENCE:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# k-NN over the org matrix — reuse similarity's z-score math (no second metric)
# ---------------------------------------------------------------------------


def _rank_matches(
    query_vec: np.ndarray,
    signatures: list,
    name_hint: Optional[str],
    k: int,
) -> list[IdentityMatch]:
    """z-score the org matrix, compute a SHAPE-FAITHFUL weighted L2 distance to each
    stored signature, and return the top-k as ranked IdentityMatches.

    Reuses ``similarity._zscore`` (the SAME z-scoring the rest of the codebase uses),
    then applies ``IDENTITY_DIM_WEIGHTS`` on the identity path ONLY: each z-scored
    component is scaled by ``sqrt(weight)`` before the L2 norm, so a weight of 1.0
    keeps a dim, 0.0 drops it. This makes the identity distance robust to pure
    re-tessellation (dropped tessellation/classifier dims) while keeping the scale-
    invariant SHAPE descriptors — WITHOUT touching ``similarity.py``'s vector used by
    the eval harness."""
    rows = np.asarray(
        [sig.signature for sig in signatures], dtype=np.float64
    )
    if rows.ndim != 2 or rows.shape[0] == 0:
        return []
    # Population mean/std over the ORG's matrix (the +1e-9 guard mirrors
    # similarity._store_from_rows so a zero-spread dim never divides by zero).
    mean = rows.mean(axis=0)
    std = rows.std(axis=0) + 1e-9

    qz = similarity._zscore(np.asarray(query_vec, dtype=np.float64), mean, std)
    Xz = similarity._zscore(rows, mean, std)

    # Shape-faithful weighting: scale each z-scored dim by sqrt(weight) so the L2
    # norm below is the weighted distance. Aligned to the signature dimensionality;
    # if a signature is an unexpected width we fall back to unit weights (never crash
    # on a legacy row).
    w = np.asarray(IDENTITY_DIM_WEIGHTS, dtype=np.float64)
    if w.shape[0] != qz.shape[-1]:
        w = np.ones(qz.shape[-1], dtype=np.float64)
    sqrt_w = np.sqrt(w)
    qz = qz * sqrt_w
    Xz = Xz * sqrt_w

    scored: list[IdentityMatch] = []
    for i, sig in enumerate(signatures):
        dist = float(np.linalg.norm(qz - Xz[i]))
        g_sim = geometry_similarity(dist)
        n_sim = name_similarity(name_hint, sig.declared_name or sig.declared_part_id)
        combined = combined_confidence(g_sim, n_sim)
        bucket = confidence_bucket(
            combined, geometry_distance=dist, name_sim=n_sim
        )
        scored.append(
            IdentityMatch(
                mesh_hash=sig.mesh_hash,
                declared_part_id=sig.declared_part_id,
                declared_name=sig.declared_name,
                program=sig.program,
                geometry_similarity=round(g_sim, 4),
                name_similarity=(round(n_sim, 4) if n_sim is not None else None),
                combined_confidence=round(combined, 4),
                confidence_bucket=bucket,
                geometry_distance=round(dist, 4),
            )
        )
    # Rank: highest combined confidence first, then nearest geometry, then a stable
    # mesh_hash tie-break (deterministic — no wall-clock).
    scored.sort(
        key=lambda m: (-m.combined_confidence, m.geometry_distance, m.mesh_hash)
    )
    return scored[: max(1, int(k))]


def select_closest_unconfirmed(matches: list[IdentityMatch]) -> Optional[IdentityMatch]:
    """Lever 2 — pick the honest LOW-confidence "closest in your library" candidate,
    or ``None``. PURE (no DB) so it is unit-testable directly.

    Returns the top match ONLY when it is a genuine, confirmable suggestion below the
    MEDIUM bar:
      * it carries a declared identity (a name or part-number to actually show);
      * its geometry proxy clears ``LOW_SUGGEST_SIM`` — non-trivial, well above the
        ≈0 an unrelated part (the torus) scores; and
      * it is separated from the runner-up by ``LOW_SUGGEST_MARGIN`` (proxy gap), so
        an ambiguous crowd of equidistant neighbours yields NO single suggestion.
    Callers use this ONLY when the result is not grounded — a grounded top match is
    carried by the confident card instead. Never auto-asserted; always a hint to
    confirm.
    """
    if not matches:
        return None
    top = matches[0]
    has_identity = bool(
        (top.declared_name and top.declared_name.strip())
        or (top.declared_part_id and top.declared_part_id.strip())
    )
    if not has_identity:
        return None
    if top.geometry_similarity < LOW_SUGGEST_SIM:
        return None
    runner_sim = matches[1].geometry_similarity if len(matches) > 1 else 0.0
    if (top.geometry_similarity - runner_sim) < LOW_SUGGEST_MARGIN:
        return None
    return top


# ---------------------------------------------------------------------------
# Public entry — the retrieval-grounding engine
# ---------------------------------------------------------------------------


async def retrieve_identity(
    session: AsyncSession,
    org_id: str,
    mesh: trimesh.Trimesh,
    *,
    name_hint: Optional[str] = None,
    k: int = 5,
    exclude_mesh_hash: Optional[str] = None,
    query_vec: Optional[np.ndarray] = None,
) -> IdentityMatchResult:
    """Ground a new part's IDENTITY by retrieving the org's closest PRIOR parts.

    1. Compute the query's 18-dim signature (``similarity.vector_for_mesh`` —
       local, NaN-safe, zero-egress). ``query_vec`` may be passed PRECOMPUTED by a
       caller that already ran the geometry pass (the /validate/cost path reuses the
       cost engine's analysed geometry — ``similarity.feature_vector`` off the same
       ``result.geometry`` + ``ctx``, byte-identical to ``vector_for_mesh(mesh)`` —
       to avoid a redundant SECOND full geometry pass at request time, F2). When
       ``query_vec`` is None it is computed from ``mesh`` here (unchanged behaviour).
    2. Load the ORG's corpus (``list_signatures`` — ``WHERE org_id = caller``).
       Empty → honest empty result (``grounded=False``, fall-back reason). NEVER
       fabricate.
    3. Geometry k-NN over the org matrix (z-scored L2, reusing ``similarity``'s
       math) → a monotonic ``geometry_similarity`` proxy per candidate.
    4. Lexical name match between ``name_hint`` and each candidate's declared
       name / part-number (documented token similarity, no external model).
    5. Blend → ``combined_confidence`` bucketed HIGH/MEDIUM/LOW (HIGH only when
       geometry is close AND name agrees, OR geometry is a near-duplicate).
    6. ``grounded`` True only when the top match clears the MEDIUM bar; caveats are
       always attached. The identity is a SUGGESTION, never an assertion.

    ``exclude_mesh_hash`` — the query part's OWN ``mesh_hash``, dropped from the
    corpus before ranking so a part can NEVER "match itself". This is robust to the
    write-back ordering: even if the current part's signature is already persisted
    (a re-verify, or retrieval called after the analysis funnel wrote it back), the
    self row is filtered out here, and ``corpus_size`` reflects the matchable PRIOR
    corpus only.
    """
    if query_vec is None:
        query_vec = similarity.vector_for_mesh(mesh)
    return await _retrieve_from_vector(
        session, org_id, query_vec,
        name_hint=name_hint, k=k, exclude_mesh_hash=exclude_mesh_hash,
    )


async def _retrieve_from_vector(
    session: AsyncSession,
    org_id: str,
    query_vec: np.ndarray,
    *,
    name_hint: Optional[str] = None,
    k: int = 5,
    exclude_mesh_hash: Optional[str] = None,
) -> IdentityMatchResult:
    """The corpus-read + rank half of ``retrieve_identity``, split out so a test can
    drive it with a precomputed query vector. Org-scoped read only."""
    signatures = await sigsvc.list_signatures(session, org_id)
    if exclude_mesh_hash:
        # Self-exclusion: a part is never its own match. Drop the query part's own
        # mesh_hash so the ranked matches — and ``corpus_size`` — are over PRIOR
        # parts only.
        signatures = [s for s in signatures if s.mesh_hash != exclude_mesh_hash]
    corpus_size = len(signatures)

    if corpus_size == 0:
        # Honest empty — the flywheel hasn't turned yet for this org.
        return IdentityMatchResult(
            grounded=False,
            matches=[],
            reason=_EMPTY_REASON,
            caveats=[_SUGGESTION_NOTE, _GEOM_PROXY_NOTE],
            provenance=PROVENANCE,
            corpus_size=0,
        )

    matches = _rank_matches(query_vec, signatures, name_hint, k)
    top = matches[0] if matches else None
    grounded = bool(top and top.confidence_bucket in ("HIGH", "MEDIUM"))

    # Lever 2 — a below-MEDIUM but real, well-separated closest part is surfaced as an
    # honest low-confidence suggestion (ONLY when NOT grounded; the confident card
    # carries a grounded top match). An unrelated part (torus) clears neither bar.
    closest_unconfirmed = (
        None if grounded else select_closest_unconfirmed(matches)
    )

    reason: Optional[str]
    if grounded:
        reason = (
            f"top match is {top.confidence_bucket} confidence "
            f"({top.combined_confidence:.0%}) — a retrieved suggestion to confirm"
        )
    elif closest_unconfirmed is not None:
        reason = (
            "no MEDIUM/HIGH match, but the closest prior part is well-separated — "
            f"surfaced as a LOW-confidence suggestion "
            f"({closest_unconfirmed.geometry_similarity:.0%} geometry) to confirm, "
            "never asserted"
        )
    else:
        reason = (
            "no HIGH/MEDIUM match in the org corpus — no identity claimed "
            "(retrieved neighbours are too dissimilar to ground an identity)"
        )

    return IdentityMatchResult(
        grounded=grounded,
        matches=matches,
        reason=reason,
        caveats=[_SUGGESTION_NOTE, _GEOM_PROXY_NOTE],
        provenance=PROVENANCE,
        corpus_size=corpus_size,
        closest_unconfirmed=closest_unconfirmed,
    )

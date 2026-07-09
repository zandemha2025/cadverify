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
# Confidence calibration — documented, honest, and deliberately conservative.
#
# geometry_similarity(distance): a z-scored L2 distance d ≥ 0 in the ORG's own
# 18-dim feature space is mapped to a similarity in (0,1] by an exponential decay
#     geometry_similarity = exp(-d / GEOM_DECAY)
# It is MONOTONIC (nearer ⇒ higher), 1.0 only at an exact-match (d=0), and a
# documented PROXY — never a probability. GEOM_DECAY is the distance at which the
# proxy falls to 1/e (~0.37): with per-dimension z-scoring, a full-population
# standard deviation of separation summed across dims lands here, so a
# near-duplicate (fraction of a std away) scores high while a genuinely different
# shape (several stds away) decays toward 0.
# ---------------------------------------------------------------------------
GEOM_DECAY = 2.5

# A geometry distance at/under this is treated as a near-DUPLICATE — close enough
# that geometry ALONE can carry a HIGH bucket even without a name agreeing. Picked
# well inside GEOM_DECAY so only a genuinely tiny separation qualifies.
GEOM_NEAR_DUPLICATE_DIST = 0.60

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

    def to_dict(self) -> dict:
        return {
            "grounded": self.grounded,
            "matches": [m.to_dict() for m in self.matches],
            "reason": self.reason,
            "caveats": self.caveats,
            "provenance": self.provenance,
            "corpus_size": self.corpus_size,
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
    """z-score the org matrix, compute L2 distance to each stored signature, and
    return the top-k as ranked IdentityMatches. Reuses ``similarity._zscore`` so the
    distance is the SAME z-scored L2 the rest of the codebase uses — no hand-rolled
    second metric."""
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
) -> IdentityMatchResult:
    """Ground a new part's IDENTITY by retrieving the org's closest prior parts.

    1. Compute the query's 18-dim signature (``similarity.vector_for_mesh`` —
       local, NaN-safe, zero-egress).
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
    """
    query_vec = similarity.vector_for_mesh(mesh)
    return await _retrieve_from_vector(
        session, org_id, query_vec, name_hint=name_hint, k=k
    )


async def _retrieve_from_vector(
    session: AsyncSession,
    org_id: str,
    query_vec: np.ndarray,
    *,
    name_hint: Optional[str] = None,
    k: int = 5,
) -> IdentityMatchResult:
    """The corpus-read + rank half of ``retrieve_identity``, split out so a test can
    drive it with a precomputed query vector. Org-scoped read only."""
    signatures = await sigsvc.list_signatures(session, org_id)
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

    reason: Optional[str]
    if grounded:
        reason = (
            f"top match is {top.confidence_bucket} confidence "
            f"({top.combined_confidence:.0%}) — a retrieved suggestion to confirm"
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
    )

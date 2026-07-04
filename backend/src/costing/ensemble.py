"""Assumption-ensemble uncertainty estimator (Moat P0 — orchestration-moat.md §4/§8).

We have ONE physics/feature cost estimator (``estimate_decision``). This module
turns its single point number into an HONEST epistemic-uncertainty band without
any ground truth, by running that same estimator under K plausible perturbations
of the rate card's most-uncertain coefficients and reporting the SPREAD.

What this is (and is not):

  * It is the first concrete step of the moat's self-calibrating ensemble
    (§4 Design A, §8 phase P0). It is *plumbing + math*, no new physics.
  * The band is an **assumption spread**, not a measured accuracy claim. Every
    coefficient range below is a documented DEFAULT assumption, not a fact. The
    band is labelled ``"assumption-ensemble, not shop-validated"``, provenance
    stays DEFAULT, and ``validated`` stays ``False``. An assumption spread can
    shape the band we show; it can NEVER present as measured accuracy.
  * The returned point estimate is BYTE-IDENTICAL to the current single-estimator
    baseline: member 0 is the unperturbed run (empty rate_overrides delta), so
    ``band.point_usd == estimate_decision(options).unit_cost_usd`` exactly.

W5 seam (documented, minimally wired via ``residual_model``):
  Once real quotes exist, a ground-truth ``ResidualModel`` (see
  ``src.costing.groundtruth`` / the MEASURED path in ``src.costing.confidence``)
  REPLACES this assumption spread with the empirical, measured band. Pass it as
  ``residual_model=`` and, per (process, qty) with >= ``MIN_RESIDUALS`` measured
  residuals, the reported p10/p50/p90 + ``validated`` come from the measured
  band instead of the perturbation spread — the assumption spread is retained
  only as the epistemic ``disagreement`` diagnostic. Until then the spread is the
  honest pre-data band.

Determinism: perturbations are a fixed low-discrepancy (Halton) grid keyed only
by member index and coefficient dimension — NO wall-clock or global randomness.
Two runs give byte-identical output.

Flag: ``COST_ENSEMBLE_ENABLED`` (default OFF). The ensemble is an ADDITIONAL,
opt-in computation. Nothing in the existing cost path constructs an ensemble, so
the existing behaviour is unchanged whether the flag is on or off; callers opt in
explicitly (``ensemble_enabled()`` + calling ``ensemble_estimate``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import NamedTuple, Optional, Sequence

from src.costing.analogy_estimator import (
    analogy_estimate, ANALOGY_PROVENANCE,
    DEFAULT_K as _AN_DEFAULT_K, DEFAULT_MIN_REAL_NEIGHBORS as _AN_MIN_REAL,
)
from src.costing.confidence import _percentile, confidence_interval
from src.costing.estimate import EstimateOptions, estimate_decision
from src.costing.rates import RATE_CARD_V0, _resolve_process_token, process_family, BAND_PCT

# ── flag ────────────────────────────────────────────────────────────────────
COST_ENSEMBLE_ENABLED = "COST_ENSEMBLE_ENABLED"


def ensemble_enabled() -> bool:
    """The ensemble is opt-in. Default OFF -> existing cost path is unchanged."""
    return os.getenv(COST_ENSEMBLE_ENABLED, "0").strip().lower() in (
        "1", "true", "yes", "on")


# How many rate-card perturbations to run (the "K" of the assumption ensemble).
DEFAULT_N_MEMBERS = 16

# Honest labels — never "measured" for the assumption path.
ASSUMPTION_LABEL = "assumption-ensemble, not shop-validated"
ASSUMPTION_METHOD = "assumption-ensemble"


# ──────────────────────────────────────────────────────────────────────────
# The UNCERTAIN coefficients — every range here is a DOCUMENTED ASSUMPTION.
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class UncertainCoefficient:
    """One rate-card coefficient we are honestly UNSURE about, with a plausible
    ± fractional range. ``rel_range`` = 0.20 means "±20% around the DEFAULT".

    ``assumption`` documents WHY the range is plausible — it is a stated belief,
    NOT a measured fact. ``clamp`` keeps a perturbed value physically valid
    (e.g. a rate fraction must stay in [0, 1])."""

    key: str                       # dotted rate-override key (rates._apply_override)
    rel_range: float               # ± fractional range around the DEFAULT value
    assumption: str                # documented rationale (a belief, not a fact)
    clamp: Optional[tuple] = None  # (lo, hi) hard bounds on the perturbed value


# The DEFAULT uncertain set: labor, key machine rates, and the model coefficients
# the source files themselves flag as "assumption, not shop-validated".
UNCERTAIN_COEFFICIENTS: list = [
    UncertainCoefficient(
        "labor_rate", 0.20,
        "Loaded shop-floor labor $/hr varies ~±20% by region/shop/burden method; "
        "the DEFAULT $35/hr is a stated assumption."),
    UncertainCoefficient(
        "machine_rate.CNC_3AXIS", 0.25,
        "3-axis mill loaded $/hr swings ~±25% with machine class, amortization and "
        "utilization accounting — a DEFAULT, not a quote."),
    UncertainCoefficient(
        "machine_rate.CNC_5AXIS", 0.25,
        "5-axis loaded $/hr is even more shop-dependent (~±25%)."),
    UncertainCoefficient(
        "machine_rate.SLS", 0.25,
        "Powder-bed bureau $/hr varies ~±25% with machine and powder handling."),
    UncertainCoefficient(
        "machine_rate.INJECTION_MOLDING", 0.25,
        "Molding press $/hr (tonnage/automation) varies ~±25%."),
    UncertainCoefficient(
        "stock_allowance", 0.15,
        "CNC billet oversize (DEFAULT ×1.10) is a stated assumption; ~±15% "
        "depending on stock forms and workholding."),
    UncertainCoefficient(
        "learning_rate", 0.05,
        "Wright learning fraction/doubling (DEFAULT 0.90) is a MODEL assumption "
        "explicitly tagged not-shop-validated in rates.py; ~±0.05.",
        clamp=(0.50, 1.0)),
    UncertainCoefficient(
        "machine_labor_frac", 0.40,
        "Operator-labor share of the machine rate (DEFAULT 0.35) is a MODEL "
        "structure tagged not-validated in rates.py; wide ~±40% until Zoox.",
        clamp=(0.0, 1.0)),
]


def scale_ranges(coeffs: Sequence[UncertainCoefficient], factor: float) -> list:
    """Return a copy of ``coeffs`` with every ± range multiplied by ``factor``.

    Widening the ranges MUST raise the ensemble's disagreement metric — this is
    the honest knob for "how unsure are we"; unit-tested."""
    return [replace(c, rel_range=c.rel_range * factor) for c in coeffs]


# First primes: one low-discrepancy Halton dimension per uncertain coefficient.
_PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]


def _halton(index: int, base: int) -> float:
    """Deterministic Halton (radical-inverse) value in (0, 1) for a positive
    integer ``index`` — a fixed low-discrepancy grid, no randomness."""
    f = 1.0
    r = 0.0
    i = index
    while i > 0:
        f /= base
        r += f * (i % base)
        i //= base
    return r


def _baseline_value(base_table: dict, key: str):
    """Resolve a coefficient's DEFAULT value from the effective base rate table,
    or ``None`` if the key does not exist in THIS build's rate card. (The DEFAULT
    uncertain set may name coefficients that only exist in newer rate cards, e.g.
    ``learning_rate`` / ``machine_labor_frac``; they are skipped where absent.)"""
    try:
        if "." in key:
            field_name, suffix = key.split(".", 1)
            pt = _resolve_process_token(suffix)
            v = base_table["process"][pt][field_name]
        else:
            v = base_table["global"][key]
    except (KeyError, TypeError):
        return None
    return None if v is None else float(v)


def applicable_coefficients(coeffs: Sequence[UncertainCoefficient],
                            base_table: dict) -> list:
    """Keep only coefficients whose key exists in THIS build's rate card."""
    return [c for c in coeffs if _baseline_value(base_table, c.key) is not None]


def build_member_overrides(coeffs: Sequence[UncertainCoefficient],
                           base_table: dict, n_members: int) -> list:
    """Build ``n_members`` DETERMINISTIC rate_override deltas.

    Member 0 is EMPTY (the unperturbed baseline — byte-identical point). Members
    1..K-1 perturb each coefficient by ``base * (1 + range * (2*halton - 1))``
    along an independent Halton dimension. Reproducible across runs/processes.
    """
    overrides: list = [{}]                      # member 0 == unperturbed baseline
    bases = [_baseline_value(base_table, c.key) for c in coeffs]
    for m in range(1, max(1, n_members)):
        ov: dict = {}
        for d, c in enumerate(coeffs):
            h = _halton(m, _PRIMES[d % len(_PRIMES)])
            delta = c.rel_range * (2.0 * h - 1.0)
            val = bases[d] * (1.0 + delta)
            if c.clamp is not None:
                lo, hi = c.clamp
                val = min(max(val, lo), hi)
            ov[c.key] = val
        overrides.append(ov)
    return overrides


# ──────────────────────────────────────────────────────────────────────────
# Output types
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class EnsembleBand:
    """The uncertainty band for one (process, quantity), from K member runs."""

    process: str
    quantity: int
    point_usd: float          # member 0 (unperturbed) — byte-identical to baseline
    mean_usd: float
    std_usd: float
    p10_usd: float
    p50_usd: float
    p90_usd: float
    disagreement_cov: float   # coefficient of variation across members (std/mean)
    n_members: int
    method: str               # "assumption-ensemble" | "measured-ensemble" (W5)
    validated: bool           # ALWAYS False for the assumption spread
    label: str
    basis: str
    member_costs: list = field(default_factory=list)
    # ── P1 analogy member (additive; only populated when a REAL k-NN contributed).
    # When empty/False these leave ``to_dict`` byte-identical to the physics-only
    # band, so an ABSTAINING analogy member is invisible in the output.
    members: list = field(default_factory=list)  # [{name,value_usd,variance_usd2,provenance,...}]
    has_real_member: bool = False                # a real ground-truth member contributed
    n_real_neighbors: int = 0                    # k-NN neighbours the analogy member used
    combined_usd: Optional[float] = None         # inverse-variance/BLUE combined value
    combined_variance_usd2: Optional[float] = None

    def to_dict(self) -> dict:
        d = {
            "process": self.process,
            "quantity": self.quantity,
            "point_usd": round(self.point_usd, 2),
            "mean_usd": round(self.mean_usd, 2),
            "std_usd": round(self.std_usd, 4),
            "p10_usd": round(self.p10_usd, 2),
            "p50_usd": round(self.p50_usd, 2),
            "p90_usd": round(self.p90_usd, 2),
            "disagreement_cov": round(self.disagreement_cov, 4),
            "n_members": self.n_members,
            "method": self.method,
            "validated": self.validated,
            "label": self.label,
            "basis": self.basis,
        }
        # Only surfaced when a REAL analogy member actually contributed — keeps the
        # physics-only / abstain path byte-identical to the pre-P1 band dict.
        if self.has_real_member:
            d["has_real_member"] = True
            d["n_real_neighbors"] = self.n_real_neighbors
            d["combined_usd"] = round(self.combined_usd, 2) if self.combined_usd is not None else None
            d["combined_variance_usd2"] = (
                round(self.combined_variance_usd2, 6)
                if self.combined_variance_usd2 is not None else None)
            d["members"] = [dict(m) for m in self.members]
        return d


@dataclass
class EnsembleResult:
    n_members: int
    method: str
    validated: bool           # False unless a REAL residual_model supplied every band
    label: str
    bands: list = field(default_factory=list)   # EnsembleBand, one per (process, qty)

    def band(self, process: str, quantity: int) -> Optional[EnsembleBand]:
        for b in self.bands:
            if b.process == process and int(b.quantity) == int(quantity):
                return b
        return None

    def to_dict(self) -> dict:
        return {
            "n_members": self.n_members,
            "method": self.method,
            "validated": self.validated,
            "label": self.label,
            "bands": [b.to_dict() for b in self.bands],
        }


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _pstd(xs: Sequence[float], mu: float) -> float:
    if len(xs) < 2:
        return 0.0
    return (sum((x - mu) ** 2 for x in xs) / len(xs)) ** 0.5


def _assumption_band_pct(process: str) -> float:
    pt = _resolve_process_token(process)
    if pt is None:
        return 40.0
    return BAND_PCT.get(process_family(pt), 40.0)


# ──────────────────────────────────────────────────────────────────────────
# The estimator
# ──────────────────────────────────────────────────────────────────────────
def ensemble_estimate(result, mesh, features, options: EstimateOptions,
                      n_members: int = DEFAULT_N_MEMBERS,
                      coefficients: Optional[Sequence[UncertainCoefficient]] = None,
                      residual_model: object = None,
                      records: Optional[Sequence] = None,
                      geometry: Optional[dict] = None,
                      analogy_k: int = None,
                      analogy_min_real: int = None) -> EnsembleResult:
    """Run ``estimate_decision`` under K deterministic rate-card perturbations and
    report the per-(process, qty) spread as an honest uncertainty band.

    Parameters
    ----------
    result, mesh, features, options
        Exactly what ``estimate_decision`` takes. NEVER mutated.
    n_members
        K — number of member runs (member 0 is the unperturbed baseline).
    coefficients
        The uncertain-coefficient set (defaults to ``UNCERTAIN_COEFFICIENTS``).
        Widen the ranges (``scale_ranges``) to raise disagreement.
    residual_model
        **W5 seam.** ``None`` (default) => the assumption spread is the band
        (validated=False, DEFAULT provenance). When a real ground-truth
        ``ResidualModel`` is supplied, each (process, qty) band with enough
        MEASURED residuals is REPLACED by the empirical band from
        ``confidence.confidence_interval`` (the measured path), and its
        ``validated`` flag follows the residuals' realness. The assumption
        spread is then kept only as the ``disagreement`` diagnostic. This is how
        the assumption band becomes a MEASURED band once quotes accumulate.
    records, geometry
        **P1 analogy seam (additive).** When both are supplied, per (process, qty)
        the assumption band is COMBINED with an independent analogy-to-quote k-NN
        member (``analogy_estimator.analogy_estimate`` over REAL ground-truth
        ``records`` with geometry near ``geometry``) by inverse-variance / BLUE
        (§6): the combined variance is provably <= the physics assumption-spread
        variance, so the reported band is TIGHTENED and centred on the combined
        value, with a ``members`` list naming each contributor. When the analogy
        member ABSTAINS (insufficient real neighbours) the band is EXACTLY today's
        physics-only assumption band — byte-identical. ``geometry`` is the QUERY
        part's MEASURED feature mapping (see ``analogy_estimator.FEATURE_KEYS``).
        Combining a real-analogy member does NOT set ``validated`` (that still
        requires the measured residual path); it sets ``has_real_member`` so the
        real-data contribution is surfaced honestly. The measured residual path,
        when it fires, takes precedence over the analogy combine.
    analogy_k, analogy_min_real
        Optional overrides for the k-NN neighbourhood size and the real-neighbour
        abstain floor (default ``analogy_estimator`` values).
    """
    coeffs = list(coefficients if coefficients is not None else UNCERTAIN_COEFFICIENTS)
    # Resolve DEFAULT coefficient values from the effective base table. Newer
    # builds carry a governed ``base_rate_table``; where absent (older builds)
    # the hardcoded ``RATE_CARD_V0`` is the base. Either way it is a table of
    # DEFAULT assumptions.
    base_table = getattr(options, "base_rate_table", None) or RATE_CARD_V0
    coeffs = applicable_coefficients(coeffs, base_table)
    member_overrides = build_member_overrides(coeffs, base_table, n_members)

    # Run every member. Member 0 uses ``options`` verbatim -> byte-identical point.
    reports = []
    for i, ov in enumerate(member_overrides):
        if i == 0 or not ov:
            reports.append(estimate_decision(result, mesh, features, options))
        else:
            merged = dict(options.rate_overrides)
            merged.update(ov)
            opts = replace(options, rate_overrides=merged)
            reports.append(estimate_decision(result, mesh, features, opts))

    # Baseline (member 0) defines the keys and the byte-identical point estimate.
    base_report = reports[0]
    keys = [(e["process"], int(e["quantity"])) for e in base_report.estimates]
    point_by = {(e["process"], int(e["quantity"])): float(e["unit_cost_usd"])
                for e in base_report.estimates}

    # Collect member unit costs per (process, qty).
    costs_by: dict = {k: [] for k in keys}
    for rep in reports:
        for e in rep.estimates:
            k = (e["process"], int(e["quantity"]))
            if k in costs_by:
                costs_by[k].append(float(e["unit_cost_usd"]))

    overall_validated = residual_model is not None
    bands: list = []
    for k in keys:
        process, quantity = k
        costs = costs_by[k]
        point = point_by[k]
        mu = _mean(costs)
        sd = _pstd(costs, mu)
        s = sorted(costs)
        cov = (sd / mu) if mu > 0 else 0.0

        # Default (pre-data) band: the assumption spread. Never "measured".
        p10 = _percentile(s, 0.10)
        p50 = _percentile(s, 0.50)
        p90 = _percentile(s, 0.90)
        method = ASSUMPTION_METHOD
        validated = False
        label = ASSUMPTION_LABEL
        basis = (f"assumption-ensemble spread of {len(costs)} perturbed rate cards "
                 f"over {len(coeffs)} DEFAULT-tagged uncertain coefficient(s); "
                 f"NOT shop-validated")

        members: list = []
        has_real_member = False
        n_real_neighbors = 0
        combined_usd = None
        combined_variance_usd2 = None
        measured = False

        # ── W5 seam: a real ResidualModel REPLACES the assumption spread with the
        # MEASURED empirical band (confidence.py measured path). ──────────────
        if residual_model is not None:
            ci = confidence_interval(
                point, assumption_band_pct=_assumption_band_pct(process),
                residual_provider=residual_model, process=process, level=0.80)
            if ci.method == "measured-residual":
                p10, p50, p90 = ci.low_usd, ci.point_usd, ci.high_usd
                method = "measured-ensemble"
                validated = ci.validated
                label = ci.label or "measured band"
                basis = ci.basis + (f"; assumption disagreement CoV={cov:.3f} retained "
                                    f"as epistemic diagnostic")
                measured = True
            else:
                overall_validated = False

        # ── P1 seam: combine an independent ANALOGY-TO-QUOTE member with the
        # physics assumption point via inverse-variance/BLUE (§6). Only when the
        # measured path did NOT fire (measured beats analogy) and real records +
        # query geometry are supplied. On ABSTAIN the band is left EXACTLY as the
        # physics-only assumption band above (byte-identical). ────────────────
        if (not measured and records is not None and geometry is not None
                and sd > 0.0):
            ae = analogy_estimate(
                process, quantity, geometry, records,
                k=(analogy_k if analogy_k is not None else _AN_DEFAULT_K),
                min_real=(analogy_min_real if analogy_min_real is not None
                          else _AN_MIN_REAL))
            if ae is not None:
                physics_var = sd * sd                       # assumption-spread variance
                blue = combine_inverse_variance(
                    [(point, physics_var), (ae.value_usd, ae.variance_usd2)])
                combined_usd = blue.value
                combined_variance_usd2 = blue.variance
                has_real_member = True
                n_real_neighbors = ae.n_used
                # Tighten the assumption band: keep its SHAPE, scale its half-widths
                # by sqrt(combined_var / physics_var) (<= 1 by BLUE), recentre on the
                # combined value. Band width can only shrink, never grow.
                scale = (combined_variance_usd2 / physics_var) ** 0.5 if physics_var > 0 else 1.0
                p10 = combined_usd + (p10 - point) * scale
                p50 = combined_usd + (p50 - point) * scale
                p90 = combined_usd + (p90 - point) * scale
                members = [
                    {"name": "physics", "value_usd": round(point, 4),
                     "variance_usd2": round(physics_var, 6),
                     "provenance": "DEFAULT assumption-ensemble spread (not shop-validated)"},
                    {"name": "analogy", "value_usd": round(ae.value_usd, 4),
                     "variance_usd2": round(ae.variance_usd2, 6),
                     "n_real_neighbors": ae.n_used,
                     "provenance": ANALOGY_PROVENANCE},
                ]
                basis = (
                    f"inverse-variance/BLUE combine of physics assumption point "
                    f"(var={physics_var:.4f}) + real analogy-to-quote k-NN "
                    f"(n={ae.n_used}, var={ae.variance_usd2:.4f}); combined var "
                    f"{combined_variance_usd2:.4f} <= min member var; band tightened. "
                    f"Real-data member contributed but NOT measured-validated "
                    f"(no held-out residual model).")

        bands.append(EnsembleBand(
            process=process, quantity=quantity, point_usd=point, mean_usd=mu,
            std_usd=sd, p10_usd=p10, p50_usd=p50, p90_usd=p90,
            disagreement_cov=cov, n_members=len(costs), method=method,
            validated=validated, label=label, basis=basis, member_costs=costs,
            members=members, has_real_member=has_real_member,
            n_real_neighbors=n_real_neighbors, combined_usd=combined_usd,
            combined_variance_usd2=combined_variance_usd2))

    overall_validated = overall_validated and all(b.validated for b in bands) and bool(bands)
    return EnsembleResult(
        n_members=len(reports),
        method=("measured-ensemble" if overall_validated else ASSUMPTION_METHOD),
        validated=overall_validated,
        label=(ASSUMPTION_LABEL if not overall_validated else "measured-ensemble band"),
        bands=bands)


# ──────────────────────────────────────────────────────────────────────────
# Inverse-variance (BLUE) combination — the estimator-space math (§6)
# ──────────────────────────────────────────────────────────────────────────
class Combined(NamedTuple):
    value: float
    variance: float


def combine_inverse_variance(values_and_vars: Sequence[tuple]) -> Combined:
    """Best linear unbiased (inverse-variance) combination of independent
    estimators (orchestration-moat.md §6).

    For unbiased estimators x_i with variances v_i, the covariance-weighted
    combination has value ``Σ (x_i / v_i) / Σ (1 / v_i)`` and variance
    ``1 / Σ (1 / v_i)`` — which is ``<= min_i v_i`` (adding a member can only
    reduce, never increase, the combined variance). Equal variances reduce to
    the plain mean. Unit-tested.

    This is the estimator-space analogue we will use once the ensemble has
    multiple *distinct* members (P1+). The current assumption ensemble has one
    physics member perturbed K ways (not K independent estimators), so this
    helper is provided and tested but not yet applied to the band above.
    """
    items = [(float(v), float(var)) for v, var in values_and_vars]
    if not items:
        raise ValueError("combine_inverse_variance requires >= 1 (value, variance)")
    if any(var < 0 for _v, var in items):
        raise ValueError("variances must be non-negative")
    # A zero-variance (perfectly precise) member dominates -> infinite weight.
    zeros = [v for v, var in items if var == 0.0]
    if zeros:
        return Combined(value=_mean(zeros), variance=0.0)
    inv = [1.0 / var for _v, var in items]
    w_sum = sum(inv)
    value = sum(w * v for (v, _var), w in zip(items, inv)) / w_sum
    return Combined(value=value, variance=1.0 / w_sum)

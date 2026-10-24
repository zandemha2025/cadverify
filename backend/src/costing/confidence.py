"""Per-estimate CONFIDENCE INTERVAL — the "± Y%" that makes a cost a claim.

The global constraint is hard: *never display or return a cost without a
confidence interval.* This module produces that interval for one estimate, in
one of two clearly-distinguished ways:

  1. ``measured-residual`` — an EMPIRICAL predictive interval built from the
     engine's MEASURED residuals against real ground-truth quotes for similar
     parts/processes (see ``src.costing.groundtruth``). This narrows as real
     ground truth accrues. It is the only interval that may carry
     ``validated=True`` — and ONLY when every residual behind it came from REAL
     (non-stand-in) ground truth.

  2. ``assumption-band`` — the fallback BEFORE any ground truth exists: the
     stated per-family assumption band (cycle-time / tooling defaults, ±40–60%)
     propagated around the point estimate. It is ALWAYS labelled
     "assumption-based, not yet validated". It is honest about being an
     assumption, not a measurement.

The split is the moat: a stand-in (synthetic) residual can shape the *spread* we
show, but it can NEVER flip ``validated`` to True — so the interval can never
masquerade as a real, measured accuracy claim. That guarantee is unit-tested.

This module is intentionally dependency-light (stdlib only) so the hot estimate
path can attach a CI to every line without importing the ground-truth machinery.
The ground-truth ``ResidualModel`` is passed in duck-typed as ``residual_provider``
(``process -> (residuals, from_real, n)``); ``None`` => assumption-band fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple

# A measured-residual interval needs at least this many residuals for the chosen
# process (or the pooled pool) before we trust its empirical quantiles; below it
# we fall back to the stated assumption band rather than over-claim from n<3.
MIN_RESIDUALS = 3

# Type of the duck-typed residual source: given a process value, return
# (residuals, from_real, n) where residuals is a sequence of signed relative
# errors e_i = predicted_i/actual_i - 1, from_real is True iff every residual
# came from REAL (non-stand-in) ground truth, and n is the count.
ResidualProvider = Callable[[Optional[str]], Tuple[Optional[Sequence[float]], bool, int]]


@dataclass
class ConfidenceInterval:
    """A cost interval with a stated, auditable basis. No naked bands."""

    low_usd: float
    high_usd: float
    point_usd: float            # bias-corrected centre (== input point for the fallback)
    level: float                # nominal coverage, e.g. 0.80
    method: str                 # "measured-residual" | "assumption-band"
    validated: bool             # True ONLY for a real-ground-truth measured interval
    n_samples: int              # residuals behind a measured interval (0 for fallback)
    basis: str                  # how the band was produced — never empty
    label: str                  # short honesty tag for display

    def __post_init__(self) -> None:
        if not self.basis or not self.basis.strip():
            raise ValueError("ConfidenceInterval.basis must explain the band (no naked CI).")

    @property
    def half_width_pct(self) -> float:
        """Symmetric-ish half-width as a % of the centre (display convenience)."""
        if self.point_usd <= 0:
            return 0.0
        return 100.0 * max(self.high_usd - self.point_usd,
                           self.point_usd - self.low_usd) / self.point_usd

    def to_dict(self) -> dict:
        return {
            "low_usd": round(self.low_usd, 2),
            "high_usd": round(self.high_usd, 2),
            "point_usd": round(self.point_usd, 2),
            "level": self.level,
            "method": self.method,
            "validated": self.validated,
            "n_samples": self.n_samples,
            "half_width_pct": round(self.half_width_pct, 1),
            "basis": self.basis,
            "label": self.label,
        }


def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile of an ascending list. q in [0, 1]."""
    n = len(sorted_vals)
    if n == 0:
        raise ValueError("percentile of empty sequence")
    if n == 1:
        return float(sorted_vals[0])
    pos = q * (n - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= n:
        return float(sorted_vals[-1])
    return float(sorted_vals[lo]) + frac * float(sorted_vals[lo + 1] - sorted_vals[lo])


def confidence_interval(
    point_usd: float,
    *,
    assumption_band_pct: float,
    residual_provider: Optional[ResidualProvider] = None,
    process: Optional[str] = None,
    level: float = 0.80,
) -> ConfidenceInterval:
    """Build the CI for one point estimate.

    ``residual_provider`` (a ground-truth ``ResidualModel`` or any callable with
    the same signature) yields measured residuals for ``process``; when it
    supplies >= ``MIN_RESIDUALS`` we return the empirical interval, otherwise we
    fall back to the stated assumption band. ``None`` always falls back.
    """
    if residual_provider is not None:
        try:
            residuals, from_real, n = residual_provider(process)
        except Exception:
            residuals, from_real, n = None, False, 0
        if residuals is not None and len(residuals) >= MIN_RESIDUALS:
            return _empirical_interval(point_usd, residuals, from_real, n, process, level)
    return _assumption_interval(point_usd, assumption_band_pct, level)


def _empirical_interval(point_usd, residuals, from_real, n, process, level) -> ConfidenceInterval:
    """Conformal-style predictive interval for the TRUE cost.

    With residual e_i = predicted_i/actual_i - 1, a prediction P implies a
    plausible true cost t_i = P / (1 + e_i). We take empirical quantiles of that
    set (e is monotone-decreasing in t, so the upper-e tail gives the lower cost).
    Honest non-parametric band; no Gaussian assumption.
    """
    s = sorted(float(e) for e in residuals if (1.0 + float(e)) > 1e-9)
    if len(s) < MIN_RESIDUALS:
        # everything was degenerate — fall back rather than fabricate
        return _assumption_interval(point_usd, 100.0 * (max(s) - min(s)) / 2.0 if s else 40.0, level)
    a = (1.0 - level) / 2.0
    e_lo = _percentile(s, a)
    e_hi = _percentile(s, 1.0 - a)
    e_med = _percentile(s, 0.5)
    low = point_usd / (1.0 + e_hi)
    high = point_usd / (1.0 + e_lo)
    centre = point_usd / (1.0 + e_med)
    scope = f"process '{process}'" if process else "pooled processes"
    origin = "REAL ground-truth quotes" if from_real else "STAND-IN (synthetic) records"
    return ConfidenceInterval(
        low_usd=low,
        high_usd=high,
        point_usd=centre,
        level=level,
        method="measured-residual",
        validated=bool(from_real),
        n_samples=int(n),
        basis=(f"empirical {int(level * 100)}% interval from {n} measured residual(s) "
               f"for {scope}, sourced from {origin}; centre is the median-bias-corrected cost"),
        label=("" if from_real
               else "STAND-IN-derived spread — NOT a validated accuracy claim"),
    )


def _assumption_interval(point_usd, assumption_band_pct, level) -> ConfidenceInterval:
    b = max(0.0, float(assumption_band_pct)) / 100.0
    return ConfidenceInterval(
        low_usd=point_usd * (1.0 - b),
        high_usd=point_usd * (1.0 + b),
        point_usd=point_usd,
        level=level,
        method="assumption-band",
        validated=False,
        n_samples=0,
        basis=(f"±{assumption_band_pct:g}% stated assumption band (cycle-time / tooling "
               f"defaults) propagated around the point estimate — no ground truth yet"),
        label="assumption-based, not yet validated",
    )

"""Leave-one-out backtest scaffold for the assumption-ensemble (Moat P0, §7.1-7.2).

Honest gating (mirrors ``src.eval.run`` and ``src.costing.groundtruth``):

  * Accuracy metrics (leave-one-out MAPE / coverage) are computed ONLY from REAL
    ground-truth records (``stand_in=False``) and ONLY when there are at least
    ``MIN_BACKTEST_REAL`` of them. Below that threshold the backtest REFUSES to
    emit accuracy — it never fabricates a number from too little (or synthetic)
    data.
  * When accuracy is refused, the backtest instead reports the ASSUMPTION-ENSEMBLE
    SPREAD over the available corpus parts (band widths + disagreement CoV). That
    spread is explicitly NOT an accuracy claim — it is "how much our own DEFAULT
    coefficient uncertainty moves the number", buildable with zero ground truth.

The heavy dependencies (engine runs over real STL parts) are injected so the
gating logic is unit-testable in isolation and this module stays additive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

# Below this many REAL held-out records we refuse leave-one-out accuracy and fall
# back to the assumption-ensemble spread. Documented, honest gate (cf.
# eval.run.MIN_HUMAN_LABELS and groundtruth.MIN_RESIDUALS).
MIN_BACKTEST_REAL = 8

ACCURACY_MODE = "leave-one-out-accuracy"
SPREAD_MODE = "assumption-ensemble-spread (REFUSED accuracy: insufficient ground truth)"


def decide_mode(n_real: int, min_real: int = MIN_BACKTEST_REAL) -> str:
    """Pure gate: enough REAL records => accuracy; else spread-only. Never
    fabricates accuracy from synthetic / too-few records."""
    return ACCURACY_MODE if n_real >= min_real else SPREAD_MODE


@dataclass
class BacktestResult:
    mode: str
    n_records: int
    n_real: int
    n_standin: int
    min_real: int
    # Accuracy block (ACCURACY_MODE only; None when refused).
    accuracy: Optional[dict] = None
    # Spread block (SPREAD_MODE): the assumption-ensemble disagreement summary.
    spread: Optional[dict] = None
    note: str = ""
    skipped: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "n_records": self.n_records,
            "n_real": self.n_real,
            "n_standin": self.n_standin,
            "min_real": self.min_real,
            "accuracy": self.accuracy,
            "spread": self.spread,
            "note": self.note,
            "skipped": self.skipped,
        }


def _spread_summary(bands: Sequence) -> dict:
    """Summarise the assumption-ensemble spread across many EnsembleBand objects.

    Reports disagreement (CoV) distribution + median band half-width — an honest
    "how unsure our DEFAULT assumptions make us", NOT an accuracy figure."""
    covs = sorted(b.disagreement_cov for b in bands)
    half_widths = []
    for b in bands:
        if b.point_usd > 0:
            half_widths.append(0.5 * (b.p90_usd - b.p10_usd) / b.point_usd)
    half_widths.sort()

    def _median(xs):
        if not xs:
            return None
        n = len(xs)
        mid = n // 2
        return xs[mid] if n % 2 else 0.5 * (xs[mid - 1] + xs[mid])

    return {
        "n_bands": len(bands),
        "median_disagreement_cov": _median(covs),
        "max_disagreement_cov": (covs[-1] if covs else None),
        "median_p10_p90_halfwidth_pct": (
            round(100.0 * _median(half_widths), 1) if half_widths else None),
        "label": "assumption-ensemble spread — NOT a validated accuracy claim",
    }


def backtest(records: Sequence,
             ensemble_bands_provider: Callable[[Sequence], Sequence],
             baseline_provider: Optional[Callable[[object], tuple]] = None,
             min_real: int = MIN_BACKTEST_REAL) -> BacktestResult:
    """Run the gated backtest.

    Parameters
    ----------
    records
        Ground-truth records (``src.costing.groundtruth.GroundTruthRecord``);
        ``stand_in`` marks synthetic ones, which NEVER count toward accuracy.
    ensemble_bands_provider
        ``records -> [EnsembleBand, ...]`` — runs the assumption ensemble over the
        parts referenced by ``records`` and returns their bands. Injected so this
        module needs no engine/corpus import to be exercised.
    baseline_provider
        ``record -> (baseline_usd, ok)`` engine cost for a record; required only
        in ACCURACY_MODE. Injected (default uses the ground-truth EngineCostCache).
    min_real
        Gate threshold (default ``MIN_BACKTEST_REAL``).
    """
    real = [r for r in records if not getattr(r, "stand_in", True)]
    standin = [r for r in records if getattr(r, "stand_in", True)]
    n_real = len(real)
    mode = decide_mode(n_real, min_real)

    # Always compute the assumption-ensemble spread (zero-ground-truth artifact).
    bands = list(ensemble_bands_provider(records))
    spread = _spread_summary(bands)

    if mode == SPREAD_MODE:
        return BacktestResult(
            mode=mode, n_records=len(records), n_real=n_real,
            n_standin=len(standin), min_real=min_real, accuracy=None,
            spread=spread,
            note=(f"Only {n_real} REAL ground-truth record(s) (< {min_real}); "
                  f"accuracy metrics REFUSED. Reporting the assumption-ensemble "
                  f"spread over available corpus parts instead — this is honest "
                  f"epistemic uncertainty, not a measured accuracy claim."))

    # ── ACCURACY_MODE: leave-one-out over REAL records only. ────────────────
    if baseline_provider is None:
        from src.costing.groundtruth import EngineCostCache
        cache = EngineCostCache()

        def baseline_provider(rec):  # type: ignore[misc]
            pred = cache.baseline(rec)
            return (pred.baseline_usd, pred.ok)

    abs_errs = []
    skipped = []
    for held in real:
        base, ok = baseline_provider(held)
        if not ok or not base or base <= 0:
            skipped.append((getattr(held, "part_id", "?"),
                            getattr(held, "process", "?"), "not costable"))
            continue
        # Leave-one-out correction from the OTHER real records of the same process.
        others = [r for r in real
                  if r is not held and r.process == held.process]
        ratios = []
        for o in others:
            ob, ook = baseline_provider(o)
            if ook and ob and ob > 0:
                ratios.append(o.actual_unit_cost_usd / ob)
        factor = _median_or_one(ratios)
        corrected = base * factor
        abs_errs.append(abs(corrected / held.actual_unit_cost_usd - 1.0))

    accuracy = None
    if abs_errs:
        abs_errs.sort()
        n = len(abs_errs)
        accuracy = {
            "n_scored": n,
            "mape_pct": round(100.0 * sum(abs_errs) / n, 1),
            "median_abs_pct": round(100.0 * abs_errs[n // 2], 1),
            "p90_abs_pct": round(100.0 * abs_errs[min(n - 1, int(0.9 * (n - 1)))], 1),
            "basis": "leave-one-out over REAL held-out records; per-process median "
                     "actual/baseline correction fitted on the OTHER real records",
        }
    return BacktestResult(
        mode=mode, n_records=len(records), n_real=n_real,
        n_standin=len(standin), min_real=min_real, accuracy=accuracy,
        spread=spread, skipped=skipped,
        note=(f"{n_real} REAL record(s) >= gate {min_real}; leave-one-out accuracy "
              f"computed from REAL records only (stand-in excluded)."))


def _median_or_one(xs: Sequence[float]) -> float:
    if not xs:
        return 1.0
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else 0.5 * (s[mid - 1] + s[mid])

"""Ground-truth loop — the engine that MEASURES and PROVES its own accuracy.

This is the answer to error-bucket #4 (irreducible shop-to-shop business
variance). You do not solve #4 with a better universal number — it does not
exist. You solve it by BINDING the engine to one shop and then MEASURING the
residual against that shop's own real quotes, on a HELD-OUT basis, so the tool
can finally say — *truthfully, computed not asserted*:

    "For YOUR shop, this part should cost $X ± Y%, validated within ±Y% across N
     real parts you gave us."

The pipeline (all local, zero network — CAD-as-IP):

    records  -> split(tuning | held-out)  -> tune(on TUNING only)
             -> evaluate(on HELD-OUT only) -> measured accuracy + ResidualModel

Three honesty rails are wired in and unit-tested:

  * **No leakage.** The split is deterministic *by part identity* — every record
    of a part lands on the same side, so a part can never appear in both tuning
    and held-out. ``tune()`` only ever sees the tuning split.
  * **Stand-in never counts as real.** Every record carries ``stand_in`` (default
    True — synthetic until proven real). Any *claimed-real* accuracy metric
    EXCLUDES stand-in records; if no real records exist the claim is ``None``
    (PENDING), never fabricated from synthetic data.
  * **Computed, not asserted.** The "±Y% on N parts" number is the measured
    distribution of held-out residuals — there is no place to type a number in.

The tuned parameter is a glass-box, editable per-process *cost-correction
multiplier* (provenance TUNED): ``corrected = baseline × factor[process]``,
``factor = median(actual / baseline)`` over the tuning split. One robust
parameter per process => low variance => it bias-corrects without overfitting
(held-out error stays ≈ the irreducible noise, it does not collapse to zero).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

from src.costing.confidence import ConfidenceInterval, confidence_interval

SCHEMA_VERSION = 1

# Local ground-truth store (CAD-as-IP: never leaves the box). Mirrors the
# shop-profile store layout — resolves regardless of cwd.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STORE_DIR = os.path.normpath(
    os.path.join(_THIS_DIR, "..", "..", "data", "ground_truth"))
DEFAULT_STORE_PATH = os.path.join(DEFAULT_STORE_DIR, "records.jsonl")

# Below this many residuals (per process or pooled) we will not advertise an
# empirical interval / per-process accuracy — small-n is reported but flagged.
MIN_RESIDUALS = 3


# ──────────────────────────────────────────────────────────────────────────
# 1. The ground-truth record + local persistence
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class GroundTruthRecord:
    """One known real cost/quote for a real part at a real quantity.

    ``stand_in`` defaults to **True**: a record is treated as synthetic — and
    excluded from every claimed-real metric — *unless explicitly marked real*.
    Fail-safe honesty: you cannot accidentally launder a synthetic number into a
    real accuracy claim by forgetting a flag.
    """

    part_id: str                      # stable identity = the STL filename (split key)
    process: str                      # engine ProcessType .value, e.g. "cnc_3axis", "sls"
    quantity: int
    actual_unit_cost_usd: float       # the KNOWN real per-unit cost/quote
    material_class: str = "polymer"
    shop: Optional[str] = None        # shop-profile name bound for this quote (None = DEFAULT card)
    region: Optional[str] = None      # explicit region override (None = let shop/option decide)
    currency: str = "USD"
    source: str = ""                  # provenance of the number (quote #, PO, vendor) — audit trail
    source_type: str = "actual"       # actual|quote|invoice|pilot|synthetic|seed|demo
    vendor_quote_id: Optional[str] = None
    invoice_date: Optional[str] = None
    actual_machine_hours: Optional[float] = None
    actual_setup_hours: Optional[float] = None
    actual_labor_hours: Optional[float] = None
    actual_inspection_hours: Optional[float] = None
    actual_cycle_seconds: Optional[float] = None
    evidence_sha256: Optional[str] = None
    evidence_uri: Optional[str] = None
    stand_in: bool = True             # True = synthetic STAND-IN; False = real ground truth
    part_path: Optional[str] = None   # explicit STL path; else resolved from part_id under parts_dir
    notes: str = ""
    # ── P1 analogy-to-quote k-NN geometry (all Optional / NULLABLE). ──────────
    # The MEASURED cost-drivers (``analogy_estimator.FEATURE_KEYS``) this record
    # carries so it can be a geometric neighbour. Populated best-effort when the
    # part's mesh resolves; any None => the analogy k-NN skips this record. Never
    # assumed — extracted from the CAD or left None.
    volume_cm3: Optional[float] = None
    surface_area_cm2: Optional[float] = None
    max_bbox_mm: Optional[float] = None
    face_count: Optional[int] = None
    created: str = field(default_factory=lambda: date.today().isoformat())
    schema_version: int = SCHEMA_VERSION

    @property
    def geometry_features(self) -> Optional[dict]:
        """The record's MEASURED geometry as the mapping ``analogy_estimator``
        consumes (``analogy_estimator._features_for`` reads this attr) — or None
        when any driver is missing, so the analogy k-NN honestly skips it. A
        property (not a dataclass field): it never enters ``to_dict``/dedup and
        stays None for records whose mesh never resolved."""
        if (self.volume_cm3 is None or self.surface_area_cm2 is None
                or self.max_bbox_mm is None or self.face_count is None):
            return None
        return {
            "volume_cm3": self.volume_cm3,
            "surface_area_cm2": self.surface_area_cm2,
            "max_bbox_mm": self.max_bbox_mm,
            "face_count": self.face_count,
        }

    def __post_init__(self) -> None:
        if not self.part_id:
            raise ValueError("GroundTruthRecord requires a part_id")
        if self.actual_unit_cost_usd is None or self.actual_unit_cost_usd <= 0:
            raise ValueError(
                f"GroundTruthRecord {self.part_id}/{self.process}: "
                "actual_unit_cost_usd must be a positive number")
        if self.stand_in and "STAND-IN" not in (self.source or "").upper():
            # make the synthetic origin self-documenting in the persisted record
            self.source = (self.source + " " if self.source else "") + "[STAND-IN — not real]"

    @property
    def key(self) -> tuple:
        return (self.part_id, self.process, int(self.quantity),
                self.shop or "", int(self.quantity))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GroundTruthRecord":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


def load_records(store_path: Optional[str] = None) -> list:
    """Load all ground-truth records from a local JSONL store (missing => [])."""
    path = store_path or DEFAULT_STORE_PATH
    if not os.path.isfile(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(GroundTruthRecord.from_dict(json.loads(line)))
    return out


def save_records(records: list, store_path: Optional[str] = None) -> str:
    """Overwrite the store with ``records`` (atomic-ish). Returns the path."""
    path = store_path or DEFAULT_STORE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for r in records:
            f.write(json.dumps(r.to_dict()) + "\n")
    os.replace(tmp, path)
    return path


def add_record(record: GroundTruthRecord, store_path: Optional[str] = None) -> str:
    """Append one record (dedup by (part_id, process, qty, shop): last wins)."""
    records = [r for r in load_records(store_path) if r.key != record.key]
    records.append(record)
    return save_records(records, store_path)


# ──────────────────────────────────────────────────────────────────────────
# 2. Deterministic tuning / held-out split — BY PART IDENTITY (no leakage)
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class SplitResult:
    tuning: list
    test: list
    test_fraction: float
    seed: int

    @property
    def tuning_part_ids(self) -> set:
        return {r.part_id for r in self.tuning}

    @property
    def test_part_ids(self) -> set:
        return {r.part_id for r in self.test}


def _part_bucket(part_id: str, seed: int) -> float:
    """Stable [0,1) hash of a part id — the SAME part always hashes the same, so
    its records never straddle the tuning/held-out boundary."""
    h = hashlib.sha256(f"{seed}:{part_id}".encode()).hexdigest()
    return (int(h[:8], 16) % 10_000) / 10_000.0


def split_records(records: list, test_fraction: float = 0.30,
                  seed: int = 1337) -> SplitResult:
    """Partition records into (tuning, held-out test) deterministically by part.

    Every record of a given part goes to the SAME side. Deterministic in the
    seed and part identity only — independent of record order — so the held-out
    set is reproducible and strictly disjoint from tuning at the part level.
    """
    # A bare hash-threshold split is deterministic, but it can put fewer than
    # MIN_RESIDUALS parts in the held-out side even when the advertised
    # eight-part calibration floor has been met.  That used to allow
    # recalibration to say "validated" while the served confidence interval
    # still had too few residuals to become empirical.  Rank the same stable
    # hashes and enforce a bounded held-out cardinality instead: three distinct
    # parts whenever the corpus is large enough, while always retaining at
    # least one tuning part.  The split remains deterministic, order-independent
    # and strictly by part identity.
    part_ids = sorted({r.part_id for r in records})
    if not part_ids:
        return SplitResult(tuning=[], test=[], test_fraction=test_fraction, seed=seed)

    ranked = sorted(part_ids, key=lambda part_id: (_part_bucket(part_id, seed), part_id))
    if len(ranked) == 1:
        n_test = 1 if test_fraction >= 1.0 else 0
    else:
        proportional = int(math.ceil(len(ranked) * max(0.0, min(1.0, test_fraction))))
        minimum = MIN_RESIDUALS if len(ranked) >= MIN_RESIDUALS + 1 else 1
        n_test = min(len(ranked) - 1, max(minimum, proportional))
    test_ids = set(ranked[:n_test])

    tuning, test = [], []
    for r in records:
        (test if r.part_id in test_ids else tuning).append(r)
    return SplitResult(tuning=tuning, test=test,
                       test_fraction=test_fraction, seed=seed)


# ──────────────────────────────────────────────────────────────────────────
# 3. Baseline engine cost for a record (cached) — drives the real engine
# ──────────────────────────────────────────────────────────────────────────
def resolve_part_path(record: GroundTruthRecord, parts_dir: Optional[str]) -> Optional[str]:
    cands = []
    if record.part_path:
        # API/CSV-supplied part paths are deliberately relative and confined to
        # the trusted corpus root.  Joining here is both the functional contract
        # and the final traversal boundary; checking a bare relative path would
        # accidentally resolve against the server process working directory.
        if os.path.isabs(record.part_path):
            # Direct dataclass callers (offline eval/tests) may still provide an
            # operator-trusted absolute path. Network ingress rejects these.
            cands.append(record.part_path)
        elif parts_dir:
            root = os.path.realpath(parts_dir)
            candidate = os.path.realpath(os.path.join(root, record.part_path))
            if candidate == root or candidate.startswith(root + os.sep):
                cands.append(candidate)
        else:
            cands.append(record.part_path)
    if parts_dir:
        cands.append(os.path.join(parts_dir, record.part_id))
        if not record.part_id.lower().endswith((".stl", ".step", ".stp")):
            cands.append(os.path.join(parts_dir, record.part_id + ".stl"))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


@dataclass
class Prediction:
    record: GroundTruthRecord
    baseline_usd: Optional[float]     # engine cost at DEFAULT/shop rates (pre-correction)
    ok: bool
    note: str = ""


class EngineCostCache:
    """Caches one estimate_decision report per (part, qty, shop, material, region)
    so N records over M parts cost M engine runs, not N."""

    def __init__(self, parts_dir: Optional[str] = None):
        self.parts_dir = parts_dir
        self._reports: dict = {}

    def _report(self, path, qty, shop, material_class, region):
        key = (path, int(qty), shop or "", material_class, region or "")
        if key in self._reports:
            return self._reports[key]
        from src.costing.cli import _run_engine
        from src.costing import estimate_decision, EstimateOptions
        result, mesh, feats = _run_engine(path)
        opts = EstimateOptions(
            quantities=[int(qty)], material_class=material_class,
            material_class_is_user=True, shop=shop,
            region=(region or "US"), region_is_user=region is not None)
        rep = estimate_decision(result, mesh, feats, opts)
        self._reports[key] = rep
        return rep

    def baseline(self, record: GroundTruthRecord) -> Prediction:
        path = resolve_part_path(record, self.parts_dir)
        if path is None:
            return Prediction(record, None, False,
                              f"part file not found for '{record.part_id}'")
        try:
            rep = self._report(path, record.quantity, record.shop,
                               record.material_class, record.region)
        except Exception as exc:  # pragma: no cover - corrupt mesh / engine error
            return Prediction(record, None, False, f"engine error: {exc}")
        if rep.status != "OK":
            return Prediction(record, None, False, f"geometry not costable ({rep.status})")
        for e in rep.estimates:
            if e["process"] == record.process and int(e["quantity"]) == int(record.quantity):
                return Prediction(record, float(e["unit_cost_usd"]), True)
        avail = sorted({e["process"] for e in rep.estimates})
        return Prediction(record, None, False,
                          f"process '{record.process}' not in costed set {avail}")


# ──────────────────────────────────────────────────────────────────────────
# 4. Tuner — fit a per-process cost-correction multiplier on the TUNING split
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class Calibration:
    """Glass-box, editable correction: corrected = baseline × factor[process].

    ``factor`` is the robust median ratio actual/baseline over the TUNING split
    (provenance TUNED). One parameter per process keeps variance low — it
    bias-corrects without memorising parts.
    """

    process_factors: dict = field(default_factory=dict)
    global_factor: float = 1.0
    n_by_process: dict = field(default_factory=dict)
    fitted_on: str = ""
    provenance: str = "TUNED"

    def factor_for(self, process: str) -> float:
        if process in self.process_factors and self.n_by_process.get(process, 0) >= 1:
            return self.process_factors[process]
        return self.global_factor

    def correct(self, baseline_usd: float, process: str) -> float:
        return baseline_usd * self.factor_for(process)

    def to_dict(self) -> dict:
        return {
            "process_factors": {k: round(v, 4) for k, v in self.process_factors.items()},
            "global_factor": round(self.global_factor, 4),
            "n_by_process": self.n_by_process,
            "fitted_on": self.fitted_on,
            "provenance": self.provenance,
        }


IDENTITY_CALIBRATION = Calibration(global_factor=1.0,
                                   fitted_on="untuned (factor = 1.0, raw engine baseline)")


def _ratios(predictions: list) -> list:
    return [(p.record, p.record.actual_unit_cost_usd / p.baseline_usd)
            for p in predictions if p.ok and p.baseline_usd and p.baseline_usd > 0]


def tune(tuning_predictions: list) -> Calibration:
    """Fit the correction from TUNING predictions ONLY. Never sees held-out."""
    by_proc: dict = {}
    all_ratios: list = []
    for rec, ratio in _ratios(tuning_predictions):
        by_proc.setdefault(rec.process, []).append(ratio)
        all_ratios.append(ratio)
    global_factor = statistics.median(all_ratios) if all_ratios else 1.0
    factors = {p: statistics.median(rs) for p, rs in by_proc.items()}
    n_by = {p: len(rs) for p, rs in by_proc.items()}
    n_parts = len({rec.part_id for rec, _ in _ratios(tuning_predictions)})
    return Calibration(
        process_factors=factors, global_factor=global_factor, n_by_process=n_by,
        fitted_on=f"tuning split: {len(all_ratios)} record(s) over {n_parts} part(s)")


# ──────────────────────────────────────────────────────────────────────────
# 5. Evaluation on the held-out split — the MEASURED accuracy (stand-in-safe)
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class Residual:
    part_id: str
    process: str
    quantity: int
    actual_usd: float
    baseline_usd: float
    corrected_usd: float
    signed_err: float          # corrected/actual - 1  (the residual that drives the CI)
    abs_err: float
    stand_in: bool


def _residuals(predictions: list, calib: Calibration) -> list:
    out = []
    for p in predictions:
        if not p.ok or not p.baseline_usd:
            continue
        corrected = calib.correct(p.baseline_usd, p.record.process)
        a = p.record.actual_unit_cost_usd
        se = corrected / a - 1.0
        out.append(Residual(
            part_id=p.record.part_id, process=p.record.process,
            quantity=int(p.record.quantity), actual_usd=a,
            baseline_usd=p.baseline_usd, corrected_usd=corrected,
            signed_err=se, abs_err=abs(se), stand_in=p.record.stand_in))
    return out


def _aggregate(residuals: list) -> Optional[dict]:
    if not residuals:
        return None
    signed = [r.signed_err for r in residuals]
    absv = sorted(r.abs_err for r in residuals)
    n = len(residuals)

    def pctile(frac: float) -> float:
        if n == 1:
            return absv[0]
        pos = frac * (n - 1)
        lo = int(pos)
        if lo + 1 >= n:
            return absv[-1]
        return absv[lo] + (pos - lo) * (absv[lo + 1] - absv[lo])

    per_proc: dict = {}
    by_p: dict = {}
    for r in residuals:
        by_p.setdefault(r.process, []).append(r)
    for proc, rs in sorted(by_p.items()):
        per_proc[proc] = {
            "n": len(rs),
            "mean_signed_pct": round(100 * statistics.mean(x.signed_err for x in rs), 1),
            "mean_abs_pct": round(100 * statistics.mean(x.abs_err for x in rs), 1),
            "median_abs_pct": round(100 * statistics.median(x.abs_err for x in rs), 1),
        }
    return {
        "n_records": n,
        "n_parts": len({r.part_id for r in residuals}),
        "mean_signed_pct": round(100 * statistics.mean(signed), 1),
        "mean_abs_pct": round(100 * statistics.mean(r.abs_err for r in residuals), 1),
        "median_abs_pct": round(100 * statistics.median(r.abs_err for r in residuals), 1),
        "p90_abs_pct": round(100 * pctile(0.90), 1),
        "band_covers_80pct": round(100 * pctile(0.80), 1),   # "±Y% covers 80% of held-out"
        "worst_abs_pct": round(100 * absv[-1], 1),
        "per_process": per_proc,
    }


@dataclass
class Evaluation:
    label: str                       # e.g. "held-out (test)"
    metrics_all: Optional[dict]      # includes stand-in — for exercising the loop
    metrics_real: Optional[dict]     # EXCLUDES stand-in — the claimed-real number (None = PENDING)
    n_real: int
    n_standin: int
    residuals: list = field(default_factory=list)

    @property
    def claim(self) -> str:
        """The one honest headline sentence for this split."""
        if self.metrics_real is not None and self.n_real >= MIN_RESIDUALS:
            m = self.metrics_real
            return (f"VALIDATED within ±{m['band_covers_80pct']:g}% across "
                    f"{m['n_parts']} real held-out part(s) "
                    f"(mean abs error {m['mean_abs_pct']:g}%).")
        if self.metrics_real is not None:
            return (
                "PENDING enough costable held-out ground truth. "
                f"Only {self.n_real} real held-out residual(s) were available "
                f"(< {MIN_RESIDUALS} required for an empirical band)."
            )
        if self.metrics_all is not None:
            m = self.metrics_all
            return ("PENDING real ground truth. "
                    f"On STAND-IN held-out data only (NOT a real accuracy claim): "
                    f"mean abs error {m['mean_abs_pct']:g}% over {m['n_parts']} part(s).")
        return "PENDING real ground truth — no held-out records could be costed."


def evaluate(predictions: list, calib: Calibration, label: str) -> Evaluation:
    """Measure error on a set of predictions. Splits real vs stand-in and makes
    the claimed-real metric EXCLUDE stand-in records (None if no real records)."""
    res = _residuals(predictions, calib)
    real = [r for r in res if not r.stand_in]
    standin = [r for r in res if r.stand_in]
    return Evaluation(
        label=label,
        metrics_all=_aggregate(res),
        metrics_real=_aggregate(real),     # None when there is no real ground truth
        n_real=len(real), n_standin=len(standin), residuals=res)


# ──────────────────────────────────────────────────────────────────────────
# 6. ResidualModel — the per-estimate CI source (callable: process -> residuals)
# ──────────────────────────────────────────────────────────────────────────
class ResidualModel:
    """Turns measured held-out residuals into a live CI source.

    Callable with the ``residual_provider`` signature expected by
    ``confidence.confidence_interval`` — ``process -> (residuals, from_real, n)``
    — so it plugs straight into ``EstimateOptions.residual_model``. It prefers
    REAL residuals; if (and only if) none exist it exposes stand-in residuals so
    the *spread* can still be exercised, but with ``from_real=False`` — which
    forces the resulting CI's ``validated`` flag to False. Stand-in data can
    shape the band, never validate it.
    """

    def __init__(self, residuals: list):
        real = [r for r in residuals if not r.stand_in]
        self.from_real = len(real) > 0
        pool = real if self.from_real else residuals
        self._by_proc: dict = {}
        for r in pool:
            self._by_proc.setdefault(r.process, []).append(r.signed_err)
        self._pooled = [r.signed_err for r in pool]

    def __call__(self, process: Optional[str]):
        proc_res = self._by_proc.get(process)
        if proc_res is not None and len(proc_res) >= MIN_RESIDUALS:
            return proc_res, self.from_real, len(proc_res)
        if self._pooled and len(self._pooled) >= MIN_RESIDUALS:
            return self._pooled, self.from_real, len(self._pooled)
        return None, self.from_real, len(self._pooled)

    def interval(self, point_usd: float, process: Optional[str] = None,
                 assumption_band_pct: float = 40.0, level: float = 0.80) -> ConfidenceInterval:
        return confidence_interval(point_usd, assumption_band_pct=assumption_band_pct,
                                   residual_provider=self, process=process, level=level)


# ──────────────────────────────────────────────────────────────────────────
# 7. The whole loop, end to end
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class LoopResult:
    n_records: int
    split: SplitResult
    calibration: Calibration
    tuning_eval: Evaluation
    heldout_eval: Evaluation
    baseline_heldout_eval: Evaluation     # held-out WITHOUT correction (overfit/uplift sanity)
    residual_model: ResidualModel
    skipped: list = field(default_factory=list)   # (record, reason) that could not be costed


def run_loop(records: list, parts_dir: Optional[str] = None,
             test_fraction: float = 0.30, seed: int = 1337,
             cache: Optional[EngineCostCache] = None) -> LoopResult:
    """records -> split -> tune(TUNING) -> evaluate(HELD-OUT). The held-out
    numbers are the measured accuracy; tuning never touches the held-out split."""
    cache = cache or EngineCostCache(parts_dir)

    # Establish costability before selecting the held-out set.  Missing source
    # artifacts are operationally useful import errors, but they are not model
    # observations and must not consume the scarce held-out slots that make an
    # empirical interval possible.  Costability depends only on the source and
    # engine execution—not on the actual-cost label—so filtering here does not
    # leak target values into tuning.
    predictions = [cache.baseline(r) for r in records]
    skipped = [(p.record, p.note) for p in predictions if not p.ok]
    costable_records = [p.record for p in predictions if p.ok]
    split = split_records(costable_records, test_fraction=test_fraction, seed=seed)
    test_ids = split.test_part_ids
    tuning_pred = [p for p in predictions if p.ok and p.record.part_id not in test_ids]
    test_pred = [p for p in predictions if p.ok and p.record.part_id in test_ids]

    calib = tune(tuning_pred)                       # TUNING ONLY
    tuning_eval = evaluate(tuning_pred, calib, "tuning")
    heldout_eval = evaluate(test_pred, calib, "held-out (test)")
    baseline_heldout = evaluate(test_pred, IDENTITY_CALIBRATION,
                                "held-out (test), UNTUNED baseline")
    # Live CI source: built from held-out residuals (prefers real; stand-in only
    # shapes the spread and stays from_real=False).
    residual_model = ResidualModel(heldout_eval.residuals)

    return LoopResult(
        n_records=len(records), split=split, calibration=calib,
        tuning_eval=tuning_eval, heldout_eval=heldout_eval,
        baseline_heldout_eval=baseline_heldout,
        residual_model=residual_model, skipped=skipped)


# ──────────────────────────────────────────────────────────────────────────
# 8. Stand-in (synthetic) data generator — to EXERCISE the loop, tagged STAND-IN
# ──────────────────────────────────────────────────────────────────────────
# A hidden per-process "shop reality" the engine baseline does NOT know about,
# plus reproducible per-(part,process) noise. The tuner must recover the hidden
# factor on the tuning split; the held-out residual then equals the irreducible
# noise — NOT zero — which is exactly what an honest accuracy demo should show.
_STANDIN_HIDDEN = {
    "sls": 1.62, "mjf": 1.55, "fdm": 1.34, "sla": 1.45, "dlp": 1.45,
    "cnc_3axis": 0.88, "cnc_5axis": 0.95, "cnc_turning": 0.82,
    "injection_molding": 1.15, "die_casting": 1.10, "sheet_metal": 0.90,
}
_STANDIN_NOISE_PCT = 15.0   # ±15% multiplicative noise => irreducible held-out floor


def _standin_noise(part_id: str, process: str) -> float:
    h = hashlib.sha256(f"noise:{part_id}:{process}".encode()).hexdigest()
    u = (int(h[:8], 16) % 10_000) / 10_000.0      # [0,1)
    return (2.0 * u - 1.0) * (_STANDIN_NOISE_PCT / 100.0)   # [-0.15, +0.15)


def make_standin_record(part_id: str, process: str, quantity: int,
                        baseline_usd: float, shop: Optional[str] = None,
                        material_class: str = "polymer") -> GroundTruthRecord:
    """Synthesize ONE clearly-tagged STAND-IN ground-truth record.

    actual = engine_baseline × hidden_factor[process] × (1 + noise). The hidden
    factor is what calibration should recover; the noise is the irreducible
    held-out error. This is NOT a real quote and is tagged so everywhere.
    """
    hidden = _STANDIN_HIDDEN.get(process, 1.0)
    actual = baseline_usd * hidden * (1.0 + _standin_noise(part_id, process))
    return GroundTruthRecord(
        part_id=part_id, process=process, quantity=int(quantity),
        actual_unit_cost_usd=round(actual, 2), material_class=material_class,
        shop=shop, stand_in=True,
        source=f"STAND-IN — not real (synthetic: baseline×{hidden:g}×(1±{_STANDIN_NOISE_PCT:g}% noise))",
        notes="Generated to EXERCISE the ground-truth loop. NOT a validated accuracy datum.")


# ──────────────────────────────────────────────────────────────────────────
# 9. Report (markdown) — honest, PENDING-aware
# ──────────────────────────────────────────────────────────────────────────
def build_report(loop: LoopResult, *, title_suffix: str = "") -> str:
    L: list = []
    he = loop.heldout_eval
    has_real = he.metrics_real is not None
    L.append(f"# ProofShape — Ground-Truth Loop: measured accuracy{title_suffix}")
    L.append("")
    L.append("**Author:** Ground-Truth-Loop-Builder (Cost-Truth cycle) · "
             "**Status:** RUNS, measured · **Network egress:** zero (CAD-as-IP)")
    L.append("")
    if not has_real:
        L.append("> **REAL ACCURACY IS PENDING REAL DATA.** Every record exercised below is "
                 "tagged **STAND-IN — not real** (synthetic, generated only to prove the loop "
                 "runs and is honest). The numbers in the *stand-in* columns are **NOT a "
                 "validated accuracy claim**. The real ±Y% awaits real quotes (the Zoox "
                 "session): drop real records in, mark them `stand_in=False`, re-run.")
    else:
        m = he.metrics_real
        L.append(f"> **{he.claim}** Computed from the held-out split only "
                 f"(stand-in records excluded from this number).")
    L.append("")

    # ---- the loop ----
    L.append("## The loop (what ran)")
    L.append("")
    L.append(f"- **Records:** {loop.n_records} total "
             f"({he.n_real + loop.tuning_eval.n_real} real, "
             f"{he.n_standin + loop.tuning_eval.n_standin} stand-in across both splits).")
    L.append(f"- **Split (seed {loop.split.seed}, {int(loop.split.test_fraction*100)}% held out, "
             f"by PART identity → no leakage):** "
             f"{len(loop.split.tuning_part_ids)} tuning part(s) / "
             f"{len(loop.split.test_part_ids)} held-out part(s); "
             f"intersection = {len(loop.split.tuning_part_ids & loop.split.test_part_ids)} (must be 0).")
    L.append(f"- **Tuned on the tuning split only:** {loop.calibration.fitted_on}.")
    if loop.skipped:
        L.append(f"- **Skipped (could not be costed):** {len(loop.skipped)} record(s) — "
                 + "; ".join(f"{r.part_id}/{r.process} ({why})"
                             for r, why in loop.skipped[:4])
                 + (" …" if len(loop.skipped) > 4 else "") + ".")
    L.append("")

    # ---- tuned correction (glass box) ----
    L.append("## Tuned correction (glass-box, editable, provenance TUNED)")
    L.append("")
    L.append("`corrected = engine_baseline × factor[process]`, "
             "`factor = median(actual / baseline)` over the tuning split:")
    L.append("")
    L.append("| process | factor | n (tuning) |")
    L.append("|---------|-------:|-----------:|")
    for p, fac in sorted(loop.calibration.process_factors.items()):
        L.append(f"| {p} | ×{fac:.3f} | {loop.calibration.n_by_process.get(p, 0)} |")
    L.append(f"| _(global fallback)_ | ×{loop.calibration.global_factor:.3f} | — |")
    L.append("")

    # ---- held-out vs tuning (no-overfit evidence) ----
    L.append("## Measured error — held-out vs tuning (no-overfitting check)")
    L.append("")
    L.append("| split | scope | n parts | mean abs err | median abs err | p90 abs err | mean signed |")
    L.append("|-------|-------|--------:|-------------:|---------------:|------------:|------------:|")
    _row(L, "tuning", loop.tuning_eval)
    _row(L, "HELD-OUT", he)
    _row(L, "held-out (UNTUNED)", loop.baseline_heldout_eval, untuned=True)
    L.append("")
    L.append("_No-overfit signal: held-out error is **not dramatically worse** than tuning "
             "error (a one-parameter-per-process median fit cannot memorise parts). Tuning "
             "uplift = the drop from the UNTUNED held-out row to the HELD-OUT row — error "
             "removed on parts the tuner never saw._")
    L.append("")
    if has_real:
        L.append("All rows above are **computed**, not asserted, and the *claimed-real* "
                 "metric uses ONLY records with `stand_in=False`.")
    else:
        L.append("**All rows above are STAND-IN.** They prove the machinery measures and "
                 "does not overfit; they are **not** a real accuracy figure.")
    L.append("")

    # ---- per-estimate CI ----
    L.append("## Per-estimate confidence interval")
    L.append("")
    rm = loop.residual_model
    src = "REAL held-out residuals" if rm.from_real else "STAND-IN held-out residuals (spread only)"
    L.append(f"Every estimate now carries a CI. With ground truth loaded, the live source is "
             f"the **{src}** (`ResidualModel`), an empirical {int(0.8*100)}% predictive band "
             f"`t = point / (1 + e_i)` over measured residuals `e_i`. Before any data exists "
             f"(or for a process with < {MIN_RESIDUALS} residuals) it falls back to the stated "
             f"assumption band, labelled *assumption-based, not yet validated*. A stand-in "
             f"residual can shape the spread but **forces `validated=False`** — it can never "
             f"present as a measured accuracy claim.")
    L.append("")

    L.append("## Honesty rails (enforced + unit-tested)")
    L.append("")
    L.append("1. **No leakage** — split is by part identity; `tune()` only sees the tuning "
             "split; tuning ∩ held-out parts = 0.")
    L.append("2. **Stand-in ≠ real** — `stand_in` defaults True; claimed-real metrics exclude "
             "stand-in; with zero real records the claim is `None` / PENDING, never fabricated.")
    L.append("3. **Computed, not asserted** — the ±Y% is the held-out residual distribution; "
             "there is no field to type an accuracy into.")
    L.append("")
    L.append("_Reproduce:_ `cd backend && PYTHONPATH=. .venv/bin/python -m src.costing.groundtruth --demo`")
    L.append("")
    return "\n".join(L)


def _row(L: list, name: str, ev: Evaluation, untuned: bool = False) -> None:
    m = ev.metrics_all
    if m is None:
        L.append(f"| {name} | — | 0 | n/a | n/a | n/a | n/a |")
        return
    scope = "stand-in" if ev.metrics_real is None else "real+stand-in"
    L.append(f"| {name} | {scope} | {m['n_parts']} | {m['mean_abs_pct']:g}% | "
             f"{m['median_abs_pct']:g}% | {m['p90_abs_pct']:g}% | {m['mean_signed_pct']:+g}% |")


# ──────────────────────────────────────────────────────────────────────────
# 10. CLI / demo
# ──────────────────────────────────────────────────────────────────────────
def _demo(parts_dir: Optional[str] = None, out_path: Optional[str] = None,
          quantities=(100,), shop: Optional[str] = None,
          processes=("sls", "mjf", "fdm", "cnc_3axis")) -> LoopResult:
    """Build STAND-IN records over calibration parts, run, and write the report."""
    from src.costing.harness import SAMPLE_PARTS, ensure_fixture_parts_dir

    parts_dir = parts_dir or ensure_fixture_parts_dir()
    cache = EngineCostCache(parts_dir)

    # Generate stand-in records: for each calibration part, for each process the
    # engine actually costs, synthesize one record per quantity.
    records: list = []
    for fname, _meta in SAMPLE_PARTS:
        path = os.path.join(parts_dir, fname)
        if not os.path.isfile(path):
            continue
        for q in quantities:
            # find which of the requested processes the engine costs for this part
            rep = cache._report(path, q, shop, "polymer", None)  # noqa: SLF001 (demo)
            costed = {e["process"] for e in rep.estimates}
            for proc in processes:
                if proc not in costed:
                    continue
                base = next(e["unit_cost_usd"] for e in rep.estimates
                            if e["process"] == proc and int(e["quantity"]) == int(q))
                records.append(make_standin_record(fname, proc, q, base, shop=shop))

    loop = run_loop(records, parts_dir=parts_dir, cache=cache)
    report = build_report(loop, title_suffix=" (STAND-IN demo)")
    out_path = out_path or os.path.normpath(
        os.path.join(_THIS_DIR, "..", "..", "..", "outputs", "groundtruth-report.md"))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(report)
    print(f"[ground-truth loop] {len(records)} STAND-IN records over "
          f"{len(loop.split.tuning_part_ids) + len(loop.split.test_part_ids)} parts")
    print(f"[ground-truth loop] {loop.heldout_eval.claim}")
    print(f"[ground-truth loop] report -> {out_path}")
    return loop


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="src.costing.groundtruth",
                                 description="ground-truth accuracy loop (local, zero network)")
    ap.add_argument("--demo", action="store_true",
                    help="generate STAND-IN records over real parts, run the loop, write report")
    ap.add_argument("--parts-dir", default=None)
    ap.add_argument("--shop", default=None, help="bind a stored shop profile for the records")
    ap.add_argument("--out", default=None, help="report output path")
    args = ap.parse_args(argv)
    if args.demo:
        _demo(parts_dir=args.parts_dir, out_path=args.out, shop=args.shop)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

# CadVerify — Ground-Truth Loop (self-measuring accuracy + per-estimate confidence)

**Author:** Ground-Truth-Loop-Builder (Cost-Truth cycle) · **Status:** built + RUNS on real
repo parts · **Network egress:** zero (CAD-as-IP) · **Date:** 2026-06-29

## What this is (and which error it characterizes)

The first three error buckets are *engineering* problems (rates → calibration; routing →
the matcher rebuild; cycle-time physics). **Bucket #4 — irreducible shop-to-shop business
variance — is not an engineering problem and has no universal answer.** You do not solve it
with a better geometry-to-cost number; that number does not exist (chasing it is what loses
the room). You solve it by **binding the engine to ONE shop and then MEASURING the residual
against that shop's own real quotes, on a HELD-OUT basis** — so the tool can finally say,
truthfully and computed (not asserted):

> *"For YOUR shop, this part should cost **$X ± Y%**, validated within **±Y%** across **N**
> real parts you gave us — and here is every driver and assumption behind it, editable."*

That sentence is the product. This module is the machine that earns the right to say it. It
builds directly on the in-tree calibration (`ShopProfile`) and routing work — it does not
rebuild them.

## The loop

```
 known real quotes ─► GroundTruthRecord store (local JSONL)
        │
        ▼
   split(tuning | HELD-OUT)        # deterministic, BY PART IDENTITY → no leakage
        │
        ├─ tune(TUNING only)  ─►  Calibration  (per-process cost-correction factor, TUNED)
        │
        ▼
   evaluate(HELD-OUT only)  ─►  measured accuracy  ("±Y% across N real parts")
        │                        + ResidualModel
        ▼
   every estimate ─► ConfidenceInterval   (measured-residual when data exists,
                                            else assumption-band, clearly labelled)
```

## How to use it

### 1. Enter a known real cost/quote

```python
from src.costing import GroundTruthRecord, add_record

add_record(GroundTruthRecord(
    part_id="bracket_A.stl",          # the STL filename = stable identity + split key
    process="cnc_3axis",              # the process actually used
    quantity=100,
    actual_unit_cost_usd=18.40,       # the REAL per-unit price you were quoted / paid
    shop="Midwest Precision CNC",     # the calibrated shop this quote came from (or None)
    material_class="aluminum",
    source="Vendor PO #44821, 2026-Q2",
    stand_in=False))                  # ← REAL data. (Default is True = synthetic/stand-in.)
```

`stand_in` **defaults to `True`** on purpose: a record is treated as synthetic — and excluded
from every claimed-real accuracy number — *unless you explicitly mark it real*. You cannot
accidentally launder a guess into a validated claim.

### 2. Run the loop

```python
from src.costing import load_records, run_loop, build_report

loop = run_loop(load_records(), parts_dir="/path/to/stls")
print(loop.heldout_eval.claim)                 # the honest one-line accuracy headline
open("outputs/groundtruth-report.md", "w").write(build_report(loop))
```

Or the CLI demo (generates STAND-IN data over real parts, runs the whole loop, writes the
report):

```
cd backend && PYTHONPATH=. .venv/bin/python -m src.costing.groundtruth --demo
```

### 3. Every estimate now carries a confidence interval

```python
from src.costing import estimate_decision, EstimateOptions
rep = estimate_decision(result, mesh, features,
                        EstimateOptions(quantities=[100],
                                        residual_model=loop.residual_model))
rep.estimates[0]["confidence"]
# {'low_usd': 14.9, 'high_usd': 21.1, 'point_usd': 17.8, 'level': 0.8,
#  'method': 'measured-residual', 'validated': True, 'n_samples': 9, ...}
```

With **no** `residual_model` bound (the pre-data default) every estimate still carries a CI —
the stated assumption band, labelled `assumption-based, not yet validated`. The moat constraint
holds unconditionally: **no cost is ever displayed or returned without a confidence interval.**

## The tuned parameter (glass-box, editable)

```
corrected = engine_baseline × factor[process]
factor[process] = median(actual / baseline)   over the TUNING split only
```

One robust parameter per process (provenance **TUNED**). One parameter per process is
deliberately low-variance: it **bias-corrects without memorising parts**, so held-out error
settles at the irreducible noise floor rather than collapsing to zero. The factor table is
printed in the report and is fully editable — it is an assumption like any other, just a
*fitted* one.

## The per-estimate confidence interval

- **measured-residual** (preferred, once ground truth exists): an empirical predictive band
  `t = point / (1 + eᵢ)` over the measured residuals `eᵢ = predicted/actual − 1` for that
  process (pooled fallback when a process has `< 3` of its own). Non-parametric — no Gaussian
  assumption. It **narrows as ground truth accrues**. Carries `validated=True` **only** when
  every residual behind it came from real (non-stand-in) data.
- **assumption-band** (fallback, before data): the stated per-family band (cycle-time/tooling
  defaults, ±40–60%) propagated around the point. Always `validated=False`, always labelled
  `assumption-based, not yet validated`.

## The honesty rails (the moat — all unit-tested)

1. **No leakage.** The tuning/held-out split is deterministic *by part identity* (hash of the
   part id), so every record of a part lands on the same side — a part can never appear in both
   sets. `tune()` only ever receives the tuning split. *Test:* corrupt every held-out actual
   cost 10× and re-tune — the calibration is byte-for-byte identical
   (`test_tuning_never_touches_heldout`).
2. **Stand-in is never counted as real.** Any *claimed-real* metric excludes `stand_in=True`
   records; with zero real records the claim is `None` / **PENDING**, never fabricated from
   synthetic data. A stand-in residual may shape a CI's *spread* but is forced to
   `validated=False`. *Tests:* `test_standin_excluded_from_claimed_real_metric`,
   `test_residual_model_standin_never_validates`.
3. **Computed, not asserted.** The "±Y% on N parts" figure is the measured held-out residual
   distribution — there is no field anywhere to type an accuracy into.

## What the STAND-IN demo proves (and what it does NOT)

Running `--demo` over 12 real automotive STL parts (48 synthetic records, 7 tuning / 5 held-out
parts) produced — see `outputs/groundtruth-report.md`:

| split | mean abs err | median | p90 |
|-------|-------------:|-------:|----:|
| tuning | 7.0% | 5.5% | 16.4% |
| **HELD-OUT (tuned)** | **8.3%** | 8.7% | 14.2% |
| held-out (UNTUNED) | 25.8% | 28.0% | 37.2% |

This demonstrates the loop is real and honest: tuning **lifts held-out accuracy 25.8% → 8.3%**
on parts the tuner never saw, and held-out error (8.3%) ≈ tuning error (7.0%) — i.e. **no
overfitting**, and it does **not** collapse to 0 (that would smell of leakage). The recovered
per-process factors (sls ×1.62, mjf ×1.58, cnc_3axis ×0.93) sit right on the hidden synthetic
truth.

**This is NOT a real accuracy claim.** Every record is tagged `STAND-IN — not real`; the demo
exists only to exercise and verify the machinery. **The real ±Y% is PENDING real
ground-truth quotes (the Zoox session).** Drop real records in, mark them `stand_in=False`,
re-run — the same code produces the validated number with `validated=True` CIs.

## Files

- `backend/src/costing/groundtruth.py` — records + local store, deterministic split, engine
  cost cache, tuner (`Calibration`), held-out `evaluate`, `ResidualModel`, `run_loop`,
  `build_report`, stand-in generator, `--demo` CLI.
- `backend/src/costing/confidence.py` — `ConfidenceInterval` + `confidence_interval()`
  (measured-residual vs assumption-band; stdlib-only so the hot path stays light).
- `backend/src/costing/estimate.py` — `EstimateOptions.residual_model` / `ci_level`; every
  serialized estimate now carries `confidence`.
- `backend/src/costing/report.py` — the decision card prints the CI under each process.
- `backend/tests/test_costing_groundtruth.py` — 22 tests (pure + engine-backed).
- `backend/data/ground_truth/records.jsonl` — the local record store (created on first write).
- `outputs/groundtruth-report.md` — the measured (STAND-IN) loop report.

## Acceptance

- **Feeding in (stand-in) ground truth yields an HONEST measured accuracy on HELD-OUT parts** —
  yes (25.8% → 8.3% held-out, computed; tuning never touched the held-out split).
- **No overfitting** — held-out error ≈ tuning error, > 0; asserted in tests.
- **Every estimate carries a confidence interval** — yes (measured-residual when data exists,
  else assumption-band labelled not-yet-validated).
- **The accuracy claim is COMPUTED, not asserted** — yes (it is the residual distribution).
- **Real accuracy is explicitly PENDING real data** — stated in the report header and here.
- **Existing tests do not regress** — the 60 costing tests still pass; `unit_cost == Σ
  line_items`, provenance tags, and G1 are intact.

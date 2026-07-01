# CadVerify — Ground-Truth Loop: measured accuracy (STAND-IN demo)

**Author:** Ground-Truth-Loop-Builder (Cost-Truth cycle) · **Status:** RUNS, measured · **Network egress:** zero (CAD-as-IP)

> **REAL ACCURACY IS PENDING REAL DATA.** Every record exercised below is tagged **STAND-IN — not real** (synthetic, generated only to prove the loop runs and is honest). The numbers in the *stand-in* columns are **NOT a validated accuracy claim**. The real ±Y% awaits real quotes (the Zoox session): drop real records in, mark them `stand_in=False`, re-run.

## The loop (what ran)

- **Records:** 48 total (0 real, 48 stand-in across both splits).
- **Split (seed 1337, 30% held out, by PART identity → no leakage):** 7 tuning part(s) / 5 held-out part(s); intersection = 0 (must be 0).
- **Tuned on the tuning split only:** tuning split: 28 record(s) over 7 part(s).

## Tuned correction (glass-box, editable, provenance TUNED)

`corrected = engine_baseline × factor[process]`, `factor = median(actual / baseline)` over the tuning split:

| process | factor | n (tuning) |
|---------|-------:|-----------:|
| cnc_3axis | ×0.929 | 7 |
| fdm | ×1.225 | 7 |
| mjf | ×1.579 | 7 |
| sls | ×1.619 | 7 |
| _(global fallback)_ | ×1.430 | — |

## Measured error — held-out vs tuning (no-overfitting check)

| split | scope | n parts | mean abs err | median abs err | p90 abs err | mean signed |
|-------|-------|--------:|-------------:|---------------:|------------:|------------:|
| tuning | stand-in | 7 | 7% | 5.5% | 16.4% | +1% |
| HELD-OUT | stand-in | 5 | 8.3% | 8.7% | 14.2% | +2.6% |
| held-out (UNTUNED) | stand-in | 5 | 25.8% | 28% | 37.2% | -19.4% |

_No-overfit signal: held-out error is **not dramatically worse** than tuning error (a one-parameter-per-process median fit cannot memorise parts). Tuning uplift = the drop from the UNTUNED held-out row to the HELD-OUT row — error removed on parts the tuner never saw._

**All rows above are STAND-IN.** They prove the machinery measures and does not overfit; they are **not** a real accuracy figure.

## Per-estimate confidence interval

Every estimate now carries a CI. With ground truth loaded, the live source is the **STAND-IN held-out residuals (spread only)** (`ResidualModel`), an empirical 80% predictive band `t = point / (1 + e_i)` over measured residuals `e_i`. Before any data exists (or for a process with < 3 residuals) it falls back to the stated assumption band, labelled *assumption-based, not yet validated*. A stand-in residual can shape the spread but **forces `validated=False`** — it can never present as a measured accuracy claim.

## Honesty rails (enforced + unit-tested)

1. **No leakage** — split is by part identity; `tune()` only sees the tuning split; tuning ∩ held-out parts = 0.
2. **Stand-in ≠ real** — `stand_in` defaults True; claimed-real metrics exclude stand-in; with zero real records the claim is `None` / PENDING, never fabricated.
3. **Computed, not asserted** — the ±Y% is the held-out residual distribution; there is no field to type an accuracy into.

_Reproduce:_ `cd backend && PYTHONPATH=. .venv/bin/python -m src.costing.groundtruth --demo`

# Zoox Calibration Session — Protocol

**Owner:** Validation-Auditor (Cost-Truth cycle) · **Date:** 2026-06-29 · **Duration:** ~60–75 min
**Goal of this meeting:** produce CadVerify's **first real, measured accuracy number** for Zoox's
shop, and make the first deposit in the ground-truth loop. Everything runs **locally, zero network
egress** (CAD-as-IP) — his geometry and his costs never leave the box.

> The sentence we are trying to earn the right to say by the end of this session:
> *"For YOUR shop, this part should cost **$X ± Y%**, validated within **±Y%** across **N** real
> parts you gave us — and here is every driver, editable."*
> Today we fill in the real **Y** and **N** for the first time. Before today, **Y is honestly
> PENDING** (the engine says so itself).

---

## 0. What he must bring (send this list ahead of time)

**5–10 real parts** for which Zoox knows, from a PO / vendor quote / internal cost roll-up:

1. The **STL or STEP file** (STEP works via gmsh; no cadquery needed).
2. The **real per-unit cost** (or quoted price) — and whether it's a *cost* or a *quoted price*.
3. The **real process actually used** (e.g. CNC 3-axis, SLS, sheet metal, injection molding).
4. The **quantity** that price was for.
5. **Which shop / vendor** produced it (so we can calibrate to that shop).
6. The **material** (class is enough: aluminum / steel / stainless / titanium / polymer).

Spread them across processes and sizes — that is what makes the accuracy number meaningful and
exposes routing edge cases. **Mix of processes > 10 parts of the same process.**

**He must also bring his shop's loaded rates** (for the profile): loaded labor $/hr, machine $/hr
per process, negotiated material lot prices $/kg, machine utilization, overhead %, target margin,
region. Approximate is fine — they're all editable and provenance-tagged in the output.

---

## 1. Build his shop profile (≈10 min) — kills the rate error (bucket #1)

This is the step the audit proved removes ~50 points of error (`truth-engine-validation.md`,
Check 1: 57.9% → 4.8% against a held-out shop's own reality). Capture his rates into a
`ShopProfile`:

```python
from src.costing import ShopProfile, save_profile
save_profile(ShopProfile(
    name="Zoox",
    region="US",
    labor_rate=...,            # his loaded shop-floor $/hr
    margin=...,                # target margin (price vs should-cost); 0 if costing not pricing
    overhead=...,              # indirect burden on conversion
    utilization=...,           # 0<u<=1
    machine_rates={"CNC_3AXIS": ..., "CNC_5AXIS": ..., "CNC_TURNING": ...,
                   "SLS": ..., "MJF": ..., "INJECTION_MOLDING": ...},
    material_prices={"@aluminum": ..., "@polymer": ..., "6061-T6 Aluminum": ...},
    region_multipliers={"labor": 1.0, "material": 1.0, "tooling": 1.0},  # pin labor=1.0: his
                       # labor_rate already encodes his region (avoids double-counting)
    source="Zoox session 2026-..., loaded rates from <his source>"))
```

Saved to `backend/data/shop_profiles/zoox.json`. Anything he can't give stays a visible `DEFAULT`
(gaps are shown, not hidden).

---

## 2. Cost every part LIVE, scored against his known truth (≈20 min) — routing hits/misses

For each part, run the engine bound to his profile and **read three things to him**: the routing
recommendation, the should-cost with its drivers + CI, and how far it is from his real number.

CLI (fastest, one part at a time):

```
cd backend && PYTHONPATH=. .venv/bin/python -m src.costing.cli <part>.stl \
    --qty <his_qty> --shop "Zoox" --material-class <class>
```

Or batch in Python (record everything as you go):

```python
from src.costing.cli import _run_engine
from src.costing import estimate_decision, EstimateOptions

result, mesh, feats = _run_engine(part_path)
rep = estimate_decision(result, mesh, feats, EstimateOptions(
        quantities=[his_qty], material_class=his_class, material_class_is_user=True,
        shop="Zoox"))
print(rep.routing["recommended_process"], rep.routing["reasoning"])   # routing hit/miss
e = next(x for x in rep.estimates if x["process"] == his_real_process) # the should-cost
print(e["unit_cost_usd"], e["confidence"], e["line_items"])           # $ + CI + drivers
```

**Fill in this scorecard live, one row per part:**

| # | part | his real process | engine recommended | routing hit? | his real $ | engine should-cost $ | abs error % | biggest driver |
|---|------|------------------|--------------------|:------------:|-----------:|---------------------:|------------:|----------------|
| 1 | | | | ✓ / ✗ | | | | |
| 2 | | | | ✓ / ✗ | | | | |
| … | | | | | | | | |

- **Routing hit/miss** = does `routing["recommended_process"]` match the process he actually used?
  This is the bucket-#2 score, recorded honestly part-by-part. A miss is a finding, not a failure —
  capture *why* (read him the `reasoning` string; often the geometry genuinely is ambiguous, or his
  part was modeled for 3D printing without molding draft).
- **abs error %** at this stage is the *pre-ground-truth* gap (rate-calibrated but un-tuned). Expect
  it to be larger than the final number — that is the whole point of step 4.
- For every dollar, show him the **line-item drivers and the CI**. Never a bare number. The CI here
  will read `assumption-based, not yet validated` — which is *correct*, because we haven't fed in
  ground truth yet. That honesty is the moat; do not paper over it.

---

## 3. Enter his real costs as ground truth (≈10 min) — the first deposit

Each known cost becomes one `GroundTruthRecord`, marked **`stand_in=False`** (real). The default is
`True`/synthetic on purpose — a real number must be *explicitly* declared real, so a guess can never
launder itself into a validated claim.

```python
from src.costing import GroundTruthRecord, add_record
add_record(GroundTruthRecord(
    part_id="<exact STL filename>",      # = stable identity + the no-leakage split key
    process="cnc_3axis",                  # the process he actually used (engine .value)
    quantity=<his_qty>,
    actual_unit_cost_usd=<his real $>,    # the REAL per-unit number
    material_class="aluminum",
    shop="Zoox",
    region="US",
    source="Zoox PO #.... / quote .... (2026-...)",   # audit trail
    stand_in=False))                      # ← REAL. This is what makes the claim real.
```

Do this for all 5–10 parts. They persist to `backend/data/ground_truth/records.jsonl` (local).

---

## 4. Run the loop → the FIRST REAL ACCURACY NUMBER (≈10 min)

```python
from src.costing import load_records, run_loop, build_report
loop = run_loop(load_records(), parts_dir="<dir with his STLs>")
print(loop.heldout_eval.claim)            # the honest one-line accuracy headline
open("outputs/zoox-accuracy.md", "w").write(build_report(loop, title_suffix=" — Zoox"))
```

`loop.heldout_eval.claim` now reads, with **real** numbers (no longer PENDING):

> *"VALIDATED within ±Y% across N real held-out part(s) (mean abs error Z%)."*

— **computed** from the held-out split, **not asserted**, with `stand_in` records excluded. That
sentence, with his Y and N, is the deliverable of this meeting. Also capture:

- `loop.calibration.to_dict()` — the per-process TUNED correction factors (glass-box, editable).
- `loop.heldout_eval` vs `loop.tuning_eval` vs `loop.baseline_heldout_eval` — the no-overfit check
  and the calibration uplift (untuned → tuned error drop), the same way the audit reported it.

**Small-N honesty (read this to him).** With 5–10 parts a 30% held-out split is only 1–3 parts, so
the *first* ±Y% is a **wide, provisional** band — honest, but small-n. State it as *"±Y% on N
parts, provisional — it tightens as you add quotes."* Two ways to firm it up in-session if he has
the parts:
- Prefer **≥8–10 parts across ≥3 processes** so each process has enough residuals (the CI wants
  ≥3 per process before it trusts an empirical band; below that it pools, then falls back to the
  labeled assumption band).
- For very small N, also report the **leave-one-out** residual (re-run holding each part out once)
  to use every part as a test point without leakage. Note this explicitly as small-n.

This is a **first deposit, not a final figure** — the number is designed to improve every time he
drops in another real quote and re-runs the same command.

---

## 5. Bind the measured CI back onto every estimate (≈5 min) — close the loop

Show him that the ground truth he just entered now **sharpens future quotes**:

```python
rep = estimate_decision(result, mesh, feats, EstimateOptions(
        quantities=[his_qty], shop="Zoox", residual_model=loop.residual_model))
rep.estimates[0]["confidence"]
# method now "measured-residual", validated=True (because his records are real),
# the band built from HIS measured residuals — narrower than the assumption band.
```

A process with ≥3 of his real residuals gets a `validated=True` measured band; everything else
stays the labeled assumption band. The product sentence is now fully wired, end to end, with his
data.

---

## What we walk out with (the meeting's outputs)

1. **`backend/data/shop_profiles/zoox.json`** — his calibrated shop, reusable for every future quote.
2. **`backend/data/ground_truth/records.jsonl`** — his first 5–10 real cost records (the seed of the
   ground-truth loop; grows forever).
3. **`outputs/zoox-accuracy.md`** — the report containing CadVerify's **first real measured ±Y%**
   for his shop, the tuned correction factors, and the no-overfit evidence — all computed, not
   asserted.
4. **The filled-in routing scorecard** (§2) — his real bucket-#2 hit-rate, with the misses and
   their geometric reasons captured as the next engineering backlog.

## The honesty rails we will NOT break in the room (the moat)

- **No bare numbers.** Every cost shown carries its driver line-items and a confidence interval.
- **No fabricated accuracy.** Until step 4 runs on his real records, the accuracy is stated as
  PENDING and the CIs read `assumption-based, not yet validated`. We do not pre-announce a Y.
- **Stand-in stays out of real claims.** Only his `stand_in=False` records feed the ±Y%.
- **Held-out, no leakage, no overfit.** Accuracy is measured on parts the tuner never saw (split by
  part identity); we show held-out ≈ tuning to prove it isn't memorized.
- **Glass-box.** Every rate, every correction factor, every assumption is visible, provenance-tagged
  (MEASURED / SHOP / USER / DEFAULT / TUNED), and editable — if he disagrees with a number, we
  change it in front of him and re-run.

## Pre-flight checklist (do before he walks in)

- [ ] Engine smoke test green: `cd backend && PYTHONPATH=. .venv/bin/python -m src.costing.cli <any sample>.stl --qty 100`
- [ ] Cost-truth tests green: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_costing_*.py tests/test_routing_sheet.py -q` (expect 96 passed)
- [ ] His STL/STEP files staged in one directory; filenames noted (they are the ground-truth keys).
- [ ] A blank copy of the §2 scorecard open and ready to type into.
- [ ] Confirm STEP parts load via gmsh (cadquery is intentionally absent — STEP still works).

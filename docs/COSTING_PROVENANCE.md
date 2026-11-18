# Costing + screen constants — the provenance ledger

Every numeric constant added to the engine's decision paths is listed here
with either a named source (**cited**) or an explicit **uncalibrated**
label including where the value sits in the published family and what
tightens it. Machine-checkable twins: `src/costing/weldment.py::PROVENANCE`
(CI fails the build if a rate lacks a row) and the clause citations carried
on every issue in `src/analysis/pressure_screen.py`.

## Pressure screen (PR #154)

| Constant | Value | Status | Source |
|---|---|---|---|
| Joint efficiency E | 0.70 | cited | ASME BPVC VIII-1 **UW-12** (Type 1 butt, no RT — assumed + stated in every message) |
| Allowable basis | S = min(2/3·Sy, Su/3.5) | cited | **ASME Section II Part D basis**, computed from declared room-temperature properties; not a table lookup; no temperature derating (stated) |
| Formula terms 0.6P / 0.4P / 2 | clause arithmetic | cited | **UG-27(c)(1)/(c)(2)** |
| Validity domain | t ≤ 0.5R or P ≤ 0.385·S·E | cited | **UG-27(c)** — outside, the screen declines |
| Coaxial bore tolerance | 10° | stated assumption | measurement choice, not a physics claim |
| API pressure range | 0 < P ≤ 1000 bar | sanitation | not a physics claim |

Independent verification: FEA (scikit-fem) vs exact Lamé ≤0.08%; the
clause's own working stress sits +1.4%…+5.4% above the Lamé inner-wall max
across t/R 0.05–0.25 — see `docs/pressure-screen-fea-verification.md`.

## Weldment fabrication (PR #155)

| Constant | Default | Status | Source / tightener |
|---|---|---|---|
| Min fillet leg 3/5/6/8/10/13 mm @ 6/12/20/38/63 mm | table | cited | **AWS D1.1 Table 5.7** (2025: Table 7.7), thicker member |
| Fillet section | leg²/2 | cited | geometry (equal-leg 90°) |
| Steel density | 7850 kg/m³ | cited | standard carbon steel |
| Cost formulation | L&O ÷ (DR × OF) + consumables | cited | Lincoln Electric cost methodology |
| Deposition rate | 1.8 kg/arc·h (4 lb/h) | **uncalibrated** | low end of published 4–8.5 lb/h GMAW range |
| Operator factor | 0.35 | **uncalibrated** | published typical 30–40% |
| Weld station rate | $85/h | **uncalibrated** | published calculator example; shop rate cards override |
| Consumables | $6/kg | **uncalibrated** | wire+gas order-of-magnitude |
| Saw area rate | 1935 mm²/min (3 in²/min) | **uncalibrated** | LENOX A36 structural chart family; SawCalc per shop |
| Setup / handling / min-charge / lot | 0.75 h / 0.05 h / $75 / 25 | **uncalibrated** | shop-specific |
| Assumption band | ±60% | house-stated | the widest tier (DED: "deposition-rate models coarse + shop-specific"); assumption-band, never validated until n≥3 REAL pairs |

Tightener: vendor quotes on weldment share links land as ground truth
(process `weldment_fab`); the org's quote count is reported in every
weldment payload's `calibration` block.

## Pre-existing house constants (reference)

- Family assumption bands (`BAND_PCT`, `src/costing/rates.py`): stated
  ±35–60% per family, pre-calibration physics — unchanged by these PRs.
- Learning curve (`src/costing/learning.py` + rate-card globals): stated
  default assumptions, applied to touch labor only — unchanged.

## What would flip a label

A constant flips from **uncalibrated** to **shop-calibrated** when a
governed rate card carries the shop's own row, or from
**assumption-band** to **measured-residual** when n ≥ 3 REAL
(non-stand-in) paired quotes exist for the family — the same rules the
per-part engine has always used (`MIN_RESIDUALS`, `confidence.py`).

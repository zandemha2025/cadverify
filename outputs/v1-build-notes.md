# CadVerify V1 — Build Notes (Builder, Cycle 2)

**Author:** V1 Builder · **Date:** 2026-06-28 · **Status:** DONE — implemented, run on real parts, tests green
**Implements:** `outputs/v1-fix-spec.md` (all 8 weaknesses). **Code:** `backend/src/costing/` (rates, drivers, cost_model, decision, estimate, report, cli). **Tests:** `backend/tests/test_costing_model.py` + `test_costing_gates.py`.

All numbers below are REAL captured CLI output from this session (not predicted). Every dollar is still a provenance-tagged `Driver` with a source string; `unit_cost == Σ line_items` (G3) is asserted on every estimate; broken geometry is still refused (G1).

---

## Exact run + test commands (reproducible)

```bash
cd /Users/nazeem/Desktop/developer/cadverify/backend
PARTS=/private/tmp/claude-501/-Users-nazeem-Desktop-developer-cadverify/3182c9c6-e59b-4394-a584-d9c4cd4ce0dc/scratchpad/parts
PY=.venv/bin/python

# Demo parts
$PY -W ignore -m src.costing.cli "$PARTS/1090523_b8dd5bfe-0a71-405c-906b-aa8dc51a6c30_EK_0BD1_ECU_Firewall_mount.stl" --qty 50,5000 --quiet
$PY -W ignore -m src.costing.cli "$PARTS/printables_122552_ThrottleBodyAdapter.stl" --qty 100,10000 --quiet
$PY -W ignore -m src.costing.cli "$PARTS/655044_..._MAF_Sensor_Adapter...stl" --quiet     # GEOMETRY_INVALID
# New flags
$PY ... --region CN              # region split (labor vs material vs tooling)
$PY ... --cavities 4 --complexity complex   # tooling cavity/complexity
$PY ... --qty 1                  # min-charge floor bites

# Tests
CADVERIFY_PARTS_DIR=$PARTS $PY -W ignore -m pytest tests/test_costing_model.py tests/test_costing_gates.py -q
```

**Test result: `26 passed in 196.32s`** (V0 was 17 passed; +9 new/updated covering the 8 fixes). The fast procedural subset (`test_costing_model.py` alone) is `12 passed in 0.08s`.

---

## BEFORE / AFTER — the 8 weaknesses (real captured numbers)

### #7 Decision-sentence incoherence (top priority) — RESOLVED
The headline make-now process is now the SAME process as the low-qty argmin recommendation (computed from one ranking, so they cannot disagree).

**ECU Firewall Mount, qty 50 / 5000:**

| | BEFORE (V0) | AFTER (V1) |
|---|---|---|
| Headline | `Make by **fdm** for ≤ ~583 units; invest in injection_molding tooling above ~583` | `Make by **mjf** (PP) — $44.13/unit at qty 50, the cheapest make-as-is option and your low-volume pick` |
| @ qty 50 recommendation | `**cnc_3axis** $43.60` (a DIFFERENT process; DFM-fail) | `**mjf** $44.13/unit (make-as-is, recommended)` |
| Coherent? | NO — headline fdm ≠ reco cnc_3axis | YES — headline **mjf** == reco **mjf** == argmin |

Real V1 decision block (ECU):
```
DECISION
  Make by mjf (PP (Polypropylene)) — $44.13/unit at qty 50, the cheapest make-as-is option
  and your low-volume pick. mjf stays cheapest up to ~739 units; above ~739, injection_molding
  is cheaper ($9.39/unit at qty 5000). Note: injection_molding requires design-for-molding —
  the part currently FAILS draft DFM (564 sidewall faces (96.9% of sidewall area) below 1.0°
  draft); the tooling cost shown is 'if redesigned for molding', not a current-capability quote.
  @ qty 50     → mjf / PP (Polypropylene) ($44.13/unit, 12.6–23.4 d)  (make-as-is, recommended)
             cheaper if redesigned: cnc_3axis $43.60/unit (remove undercuts)
  @ qty 5000   → mjf / PP (Polypropylene) ($43.98/unit)  (make-as-is, recommended)
             cheaper if redesigned: injection_molding $9.39/unit (add draft, tooling-dominated) ← crossover
```
Throttle adapter (qty 100/10000): BEFORE headline **fdm** but @100 reco **cnc_turning**; AFTER headline **mjf $7.25** == @100 reco **mjf $7.25**. Coherent. The `test_g4_decision_coherence_across_parts` gate loops the real-parts set and asserts `make_now_process == recommendation[q_lo].process` and that it is DFM-ready for every OK part.

### #6 DFM-fail process headlined — RESOLVED
- BEFORE: headline asserted "invest in **injection_molding** tooling above ~583" — a process the engine says the part FAILS (no draft).
- AFTER: the headline make process is drawn ONLY from DFM-ready make candidates (mjf). Injection molding appears as a tier-2 **"cheaper if redesigned"** line + an explicit Note: *"requires design-for-molding — the part currently FAILS draft DFM (564 sidewall faces …); the tooling cost shown is 'if redesigned for molding', not a current-capability quote."* Never asserted as current capability.

### #2 AM cycle = single isolated build (machine was 82% of unit) — RESOLVED
Build-plate nesting: powder-bed/DLP per-part machine = full-build-job duration ÷ `parts_per_build`. FDM/SLA stay serial (per-part) — physically honest, stated not hidden.

| part / process (qty) | BEFORE machine | BEFORE unit | AFTER machine | AFTER unit | nesting |
|---|---|---|---|---|---|
| ECU SLS (q50) | $103.82 (82% of unit) | $126.12 | **$37.50** | **$47.25** | 30.0hr build ÷ **16** parts/build |
| ECU MJF (q50) | $102.13 | $120.11 | **$37.16** | **$44.13** | 15.2hr build ÷ **9** parts/build |
| ECU FDM (q50) | $43.82 (serial) | $55.02 | **$43.82** (unchanged) | **$57.24** | serial — honest per-part, stated |
| Throttle SLS (q100) | $23.29 | $41.15 | **$4.14** | **$7.42** | 30.0hr ÷ **145** parts/build |
| Throttle MJF (q100) | $22.61 | $40.29 | **$3.89** | **$7.25** | 15.2hr ÷ **86** parts/build |

Real machine driver now states the nesting (glass box):
`machine_cost $37.50 [DEFAULT 1.8750 hr × $20/hr × region-labor ×1 [build-job 600mm ÷ 20mm/hr = 30.0hr full build ÷ 16 parts/build (packing 0.1, env (340, 340, 600)) = 1.875hr/part] ±40%]`

Note: for the LARGE flat ECU bracket (160 mm, nests only 16/plate) the per-part machine is still the biggest single line ($37.50 of $47.25 = 79%), but it is no longer the structurally-broken $103.82-of-$126 isolated build — nesting cut it to isolated/n (n=16). For the SMALL throttle part the machine drops to 56% of unit. The `test_nesting_reduces_powderbed_machine` gate asserts `machine ≤ isolated/2` and `< V0 $103.82`; the `test_small_part_am_not_overcosted` gate asserts throttle SLS machine `< 70%` of unit.

### #1 Small-part AM over-costed (flat $17.50 post-labor) — RESOLVED
Post-labor split into per-part finishing + per-build bulk (depowder) amortized over `parts_per_build`. Powder-bed depowder (0.50 hr) is one bulk op per plate; only 0.08 hr/part finishing stays per-part.

| part / process (qty) | BEFORE labor | BEFORE unit | AFTER labor | AFTER unit |
|---|---|---|---|---|
| Throttle SLS (q100) | $17.50 (0.5hr flat) | $41.15 | **$2.92** (0.08/part + 0.5/build ÷145) | **$7.42** |
| Throttle MJF (q100) | $17.50 | $40.29 | **$3.00** | **$7.25** |
| Throttle FDM (q100) | $8.75 | $17.44 | **$7.10** (serial split) | **$15.96** |

Throttle small-part AM now lands in the validation-packet's independent $4–8 ballpark (B-1), not $40+.

### #3 No minimum-charge / lot floor — RESOLVED
Per-process `min_charge × n_setups` order floor, clamped as the LAST step; the delta is booked as its own line item so Σ = unit holds.

Real capture — throttle **cnc_turning at qty 1**:
```
cnc_turning / Delrin (POM)    qty 1: $90.00/unit    ±50%
   min_charge_floor $57.74  [DEFAULT shop/order minimum $90/lot × 1 lots ÷ 1 = $90.00/unit floor (applied)]
   line items Σ = $90.00 (= amortized_fixed $17.50 + material $0.14 + machine $4.11 + labor $10.50 + min_charge_floor $57.74)
```
BEFORE V0 the same order computed $14.93 with no floor (could sink below any real shop minimum). AFTER it clamps to the $90 CNC shop minimum. At production qty the floor is negligible and adds no line item.

### #4 One flat region scalar on everything — RESOLVED
Three independent region vectors (`region_labor`, `region_material`, `region_tooling`). Commodity material (resin/billet on global indices) does NOT scale with regional shop labor.

Real capture — **ECU SLS, --region CN**:
```
material_cost $4.36  [... × region-material ×0.98]      <- commodity, NOT discounted like labor
machine_cost  $20.62 [... × region-labor ×0.55]         <- loaded labor index
labor_cost    $2.14  [... × region-labor ×0.55]
region_split  0 CN   [USER labor ×0.55 · material ×0.98 · tooling ×0.45]
```
BEFORE V0 applied a single CN ×0.65 to material+machine+material+tooling alike (the "CN ×0.65 on a resin PO" bug). The `test_region_split_material_not_labor_scaled` gate asserts CN material ratio ≈0.98 while machine ratio ≈0.55 (they differ).

### #5 Tooling = 4-bucket step on max-bbox only — RESOLVED
Tooling now `size-tier base × n_cavities^0.70 × complexity_factor`; per-shot machine couples to cavities (`÷ n_cavities`). DEFAULT (1 cav, moderate) reproduces V0 tooling exactly (no silent change).

Real capture — **ECU injection_molding, --cavities 4 --complexity complex**:
```
tooling_cost $118,755.71 [DEFAULT size tier L (max bbox 160mm) × 4 cav^0.7 (=2.64) × complex (=1.50) = $118,756; ±60%, OVERRIDABLE]
machine_cost $0.38       [DEFAULT 0.0337 hr × $45/hr ÷ 4 cavities × region-labor ×1 ...]
```
DEFAULT 1-cav moderate → tooling $30,000 (= V0), machine $1.52. The realistic trade is visible: raising cavities raises tooling (4^0.7) but lowers per-part machine (/4).

### #8 One setup over the whole lot (optimistic) — RESOLVED
Setup recurs per lot: `ceil(qty / lot_size)` setups (CNC re-fixture every 100 units; AM = one setup per build = `parts_per_build`).

Real capture — **ECU cnc_3axis** (lot_size 100):
```
cnc_3axis q50:   setup/unit $0.5250  (setup 0.75hr × $35/hr × ceil(50/100) = 1 setups ÷ 50)
cnc_3axis q5000: setup/unit $0.2625  (setup 0.75hr × $35/hr × ceil(5000/100) = 50 setups ÷ 5000)
```
BEFORE V0 at q5000 amortized ONE setup over 5000 → $26.25/5000 = **$0.0053/unit** (≈$0, understated). AFTER it recurs 50× → **$0.2625/unit** stays realistic at volume. `test_per_lot_setup_recurs` asserts total setup at q200 is ~2× total at q100 (per-lot, not ÷2).

---

## G1 robustness — UNTOUCHED (still refuses broken geometry)
Real capture — broken **MAF Sensor Adapter** (vol=0, non-watertight):
```
Geometry: 0 cm³ · 173.8×127.5×104.1 mm · watertight ✗ · 18028 faces        [MEASURED]
GEOMETRY INVALID — repair required (volume ≤ 0 / non-watertight). No cost produced.
```
Zero estimates, no decision. The engine's raw DFM table still shows `sls pass` underneath — the cost layer refuses to monetize it (the original teardown bug stays dead).

---

## Invariants preserved (Validation-Auditor contract)
- **Σ(line_items) == unit_cost** asserted on every estimate (`est.assert_sums()`), including when the min-charge floor adds its own line item. Verified across all estimates on the block, ECU, and throttle.
- **Every Driver has a non-empty source + Provenance tag** — new drivers (`parts_per_build`, `region_split`, `min_charge_floor`, cavity/complexity in `tooling_cost.source`, nesting in `machine_cost.source`, per-lot in `setup_cost.source`) all carry sources. DEFAULTs flip to USER when overridden (e.g. `--region CN` → region_split USER; `--cavities 4` → n_cavities USER).
- **Zero network egress** — no new imports beyond stdlib + `src.analysis`/`src.profiles`; G7 socket-block test still passes.
- **Legacy `profile_matcher._estimate_cost_factor`** — never imported, never surfaced.
- **4-key `line_items` shape** ({amortized_fixed, material, machine, labor}) kept; `amortized_fixed` now bundles tooling@region_tooling + setup@region_labor; `min_charge_floor` appended only when it bites.

## Acceptance-test checklist (done = RUNS on real parts)
- [x] Headline make-now process EQUALS low-qty recommendation (ECU mjf, throttle mjf; gate loops all parts)
- [x] Small-part AM cost drops to defensible band via nesting (throttle SLS $41.15 → $7.42)
- [x] Min-charge floor visible (throttle cnc_turning q1 → $90.00 with floor line item)
- [x] Region split visible (CN: material ×0.98 vs labor ×0.55)
- [x] Per-lot setup (cnc_3axis q5000 setup $0.26/unit, was $0.005)
- [x] Cavity/complexity tooling (IM 4-cav complex → $118,756; machine ÷4)
- [x] Every $ provenance-tagged and Σ == total
- [x] Broken MAF still GEOMETRY_INVALID
- [x] Tests pass: **26 passed** (was 17)

## Notes / honest residuals
- For the large flat ECU bracket, nested powder-bed machine is still the single largest line (79% of a much smaller $47.25). This is correct, not a bug — a 160 mm part only nests 16/plate. Stated in the machine driver source.
- Lead-time production-days grow with per-part machine_hr × qty on a single 8 hr/day machine, so high-qty AM lead times are large (e.g. mjf q5000 ≈ 744–1382 d). The spec (§10) left the lead-time formula unchanged; nesting correctly SHRINKS per-part production time vs V0. A multi-machine/parallel-build lead-time model is a future refinement, not a V1 fix-spec item.
- The §13 accuracy-harness (`harness.py` + `test_costing_accuracy.py` + `accuracy-report.md`) is a separate, larger deliverable in the fix-spec build order; this build delivered the 8 cost-model fixes + their test coverage. The harness is not yet built.

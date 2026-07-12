# CadVerify V1 — Validation Packet (Validation-Auditor)

**Author:** Validation-Auditor agent · **Date:** 2026-06-28 · **Verdict: COMPLETE — ship the V1 demo.**
**Supersedes:** the V0 validation packet. The 8 known V0 weaknesses (old Section B) are now **fixed and traceable**; see the audit at `outputs/audit-v1.md` for the line-by-line evidence and `outputs/accuracy-report.md` for the measured error characterization.
**Audience for the demo:** Zoox Head of Manufacturing (runs aPriori-class tooling; knows real cycle times, powder-bed nesting, and automotive volumes; will catch a fabricated number or an incoherent decision sentence in seconds).

**What changed since V0:** the top-priority decision-sentence incoherence is gone (headline make-now process now equals the low-qty argmin recommendation, single-sourced); build-plate nesting fixed the 82%-machine artifact; per-process min-charge floors, a split region model, cavity/complexity tooling, and per-lot setup all landed; and the make-vs-buy headline no longer asserts a process the part currently fails. Absolute should-cost is now **measured** against independent local bands (±40-60%, characterized per process), not asserted.

This packet stays adversarial on purpose. V1 survives because every number is provenance-tagged, sums to its total, traces to a MEASURED driver × a stated DEFAULT, and broken geometry is still refused outright. It still does **not** claim absolute should-cost accuracy to two sig figs — and it says so. Read Section B aloud **before** the live run.

---

## 0. Audit result at a glance

| Check | What I tested | Result | Note |
|---|---|---|---|
| **1 — Coherence (#7)** | Headline make-now process == low-qty argmin recommendation, on real parts | **PASS** | ECU + throttle: headline **mjf** ≡ low-qty reco **mjf** ≡ DFM-ready argmin. Single ranking — cannot disagree. The V0 contradiction is gone. |
| **2 — Defensible numbers** | V1 $/unit vs independent math + the measured accuracy harness | **PASS** | ECU SLS $47.25 re-derived to the cent from raw geometry; small-part AM now in the independent band; floors + tooling in sane bands. |
| **3 — Explainability / invariants** | Σ(lines)=unit, provenance on every driver, toy model unsurfaced | **PASS** | `assert_sums()` enforces Σ=total (incl. the min-charge floor line); every new driver carries a source + tag; legacy `cost_per_cm3` never surfaced. |
| **4 — Robustness (G1)** | Broken MAF geometry refused | **PASS** | vol=0 → `GEOMETRY_INVALID`, zero estimates, no verdict surfaced. |
| **5 — CAD-as-IP** | Network/exfil scan + the G7 + harness socket tests | **PASS** | Costing imports stdlib + local engine only; zero network primitives; both socket-block tests succeed. |

**Tests: `36 passed in 413.91s`** (V0 was 17; +9 for the 8 weakness fixes, +10 for the new accuracy harness). No coherence bug, no broken invariant, no fabricated number.

> **Cycle 3 update (2026-06-28 — audited, `outputs/audit-c3.md`):** the two residuals this packet flagged in §B.2 are now **fixed and verified** — **R-a high-qty AM lead time** (R1 finite-capacity pool: ECU mjf q5000 744–1382 d → **49.7–92.3 d**) and **R-b serial-AM +70% high** (R2 XY build-plate nesting: accuracy **C2 FAIL → PASS**, fdm median +0.75→+0.38, sla +0.61→+0.35, Overall **PASS**). Both new assumptions are inspectable, provenance-tagged DEFAULT drivers, overridable → USER. The decision layer is now exposed as an authenticated endpoint **`POST /api/v1/validate/cost`** (analyst role + kill-switch + rate-limit; **zero CAD persistence, zero network egress**; broken geometry → clean structured **400 GEOMETRY_INVALID**, not a 500). Required suite now **`48 passed in 380.56s`** (40 costing + 8 API). No regression, no fabricated number.

---

## A. THE DEMO SCRIPT — run this, in this order, on real parts

Setup (verified working this session):
```bash
cd backend
PARTS="${CADVERIFY_REAL_PARTS_DIR:?Set this to the reviewed, licensed real-part corpus}"
PY="${PYTHON:-.venv/bin/python}"
```

### Beat 1 — Lead with the honesty gate (kill the teardown bug first)
> "Before any number: the old engine confidently passed *broken* geometry and printed a cost. Watch what we do now."
```bash
$PY -W ignore -m src.costing.cli \
  "$PARTS/655044_0b409a7e-0e9d-424a-81ae-5261cd5f4181_MITSUBISHI_LANCER_1993-MAF_Sensor_Adapter_for_High_Flow_Air_filetr.stl" --quiet
```
Expected: `Geometry: 0 cm³ ... watertight ✗ → GEOMETRY INVALID — repair required. No cost produced.` Zero estimates. **This is the trust-builder; do it first.** The engine's raw DFM table still shows `sls pass` underneath — point at it: *"that's the old confident-pass; our cost layer refuses to monetize it."*

### Beat 2 — The explainable should-cost (the glass box), now correctly nested
```bash
$PY -W ignore -m src.costing.cli \
  "$PARTS/1090523_b8dd5bfe-0a71-405c-906b-aa8dc51a6c30_EK_0BD1_ECU_Firewall_mount.stl" \
  --qty 50,5000 --quiet
```
Read the SLS line items aloud — and call out the nesting (this is what a powder-bed cost engineer attacks first):
```
sls / PA12 (Nylon 12)    qty 50: $47.25/unit
  material  $4.45  [MEASURED 66.79 cm³ × 1.01 g/cm³ × $60/kg × 1.10 scrap × region-material ×1]
  parts_per_build 16 [DEFAULT packing 0.10 × env (340,340,600) ÷ part bbox+5mm = 16 parts/build]
  machine   $37.50 [DEFAULT build-job 600mm÷20mm/hr = 30.0hr ÷ 16 parts/build × $20/hr ±40%]
  labor     $3.89  [DEFAULT finish 0.08hr/part + depowder 0.50hr/build ÷ 16 × $35/hr]
  line items Σ = $47.25
```
> "Every number traces to a driver. The machine line *states* its nesting assumption — 30-hour full build, 16 parts on the plate. In V0 this read $103.82 for one isolated bracket; that was structurally wrong and a powder-bed expert would have called it. The DEFAULTs are *my* assumptions — and they're yours to change."

### Beat 3 — The COHERENT decision (the fix that matters most)
Same ECU output, bottom of card:
```
DECISION
  Make by mjf (PP) — $44.13/unit at qty 50, the cheapest make-as-is option and your low-volume pick.
  mjf stays cheapest up to ~739 units; above ~739, injection_molding is cheaper ($9.39/unit at qty 5000).
  Note: injection_molding requires design-for-molding — the part currently FAILS draft DFM (564 sidewall
        faces below 1.0° draft); the tooling cost shown is 'if redesigned for molding', not a current quote.
  @ qty 50   → mjf / PP  $44.13/unit  (make-as-is, recommended)
               cheaper if redesigned: cnc_3axis $43.60 (remove undercuts)
  @ qty 5000 → mjf / PP  $43.98/unit  (make-as-is, recommended)
               cheaper if redesigned: injection_molding $9.39 (add draft, tooling-dominated) ← crossover
```
> "One make-now process — **mjf** — is the headline, the low-quantity pick, and the cheapest DFM-ready make option. They're computed from the *same* ranking, so they can't contradict each other. (In V0 the headline said 'fdm' while the low-qty recommendation said 'cnc' — three different processes. That's fixed.) The molding route is shown *conditionally* — it's cheaper at volume only *if you redesign the part for draft*, which it currently fails. We tell you that, not hide it."

### Beat 4 — Override live, watch the decision move (the differentiation vs a black box)
```bash
$PY -W ignore -m src.costing.cli \
  "$PARTS/1090523_..._ECU_Firewall_mount.stl" \
  --qty 50,5000 --tooling INJECTION_MOLDING=60000 --quiet      # or: --cavities 4 --complexity complex
```
> "You don't believe my $30k tool? Type your number — the crossover moves right and the figure flips to `USER` provenance. Or tell me it's a 4-cavity complex tool: `--cavities 4 --complexity complex` → tooling $118,756 and per-part machine drops /4. **You change it, the model recomputes locally in under a second.** That's the answer to 'where did this number come from?'"

### Beat 5 — Sane routing + the floors that keep us honest at the edges
```bash
$PY -W ignore -m src.costing.cli "$PARTS/printables_122552_ThrottleBodyAdapter.stl" --qty 100,10000 --quiet
$PY -W ignore -m src.costing.cli "$PARTS/printables_122552_ThrottleBodyAdapter.stl" --qty 1 --quiet
```
> "The old engine put a flat plastic bracket on a lathe in Inconel 718 — turning only appears for a genuine rotational axis now. And a one-off turned part clamps to the **$90 shop minimum** (`min_charge_floor` line, Σ still holds) instead of computing an impossible $14.93. Small-part SLS is **$7.42**, not V0's $41 — because we nest 145 of them on the plate. Every one of those is a number a cost engineer would otherwise reject."

**Timing/positioning:** every run is < 12 s, fully local, zero network — "your CAD never left this laptop." (Beat 1 ≈ 3.7 s; ECU ≈ 0.4 s observed.)

---

## B. WEAKNESS LIST — V1 (what is now defensible vs what remains)

The framing that holds: **V1 stands behind the decision (crossover quantity + make-vs-buy direction), and now also behind a *measured* absolute-cost band — not the absolute dollar to two sig figs.** Every figure is a stated-band estimate you can override, not a hidden assumption.

### B.1 — NOW FIXED (the 8 V0 weaknesses — say "we closed these since the last review")

1. **Small-part additive over-cost — FIXED.** Flat $17.50 post-labor is split into per-part finishing + per-build bulk (depowder) amortized over the plate. Throttle SLS **$41.15 → $7.42**, in the independent volumetric band ($4.70-$22.22).
2. **AM single-isolated-build (82%-machine artifact) — FIXED.** Build-plate nesting: powder-bed/DLP per-part machine = full-build-job ÷ parts-per-build. ECU SLS machine **$103.82 → $37.50** (30 hr build ÷ 16). FDM/SLA stay serial (genuinely per-part) — stated, not hidden.
3. **No minimum-charge / lot floor — FIXED.** Per-process `min_charge × n_setups` order floor, clamped last, booked as its own line item. Throttle cnc_turning **q1 → $90.00** (was an unfloored $14.93).
4. **Flat region scalar on everything — FIXED.** Three independent vectors. CN: commodity **material ×0.98** (global feedstock) vs **labor ×0.55** vs **tooling ×0.45**. The "CN ×0.65 on a resin PO" bug is gone.
5. **Tooling 4-bucket step — FIXED.** `size-tier × n_cavities^0.70 × complexity`. 4-cavity complex ECU tool = **$118,756**, per-part machine ÷4. DEFAULT (1-cav, moderate) = $30,000 (= V0, no silent change). Both USER-overridable (`--cavities`, `--complexity`).
6. **DFM-fail process headlined — FIXED.** The headline make process is drawn only from DFM-ready make candidates; injection molding appears as a tier-2 "cheaper if redesigned" line + an explicit "currently FAILS draft DFM" note. Never asserted as current capability.
7. **Decision-sentence incoherence — FIXED (top priority).** Headline make-now ≡ low-qty recommendation ≡ DFM-ready make champion, all from one ranking. Verified on the ECU mount (mjf) and throttle (mjf), and looped across the real-parts set in a gate test.
8. **One-setup-over-the-whole-lot — FIXED.** Setup recurs `ceil(qty/lot_size)`: CNC re-fixtures every 100 units, AM re-sets per build. ECU cnc_3axis q5000 setup is now $0.26/unit, not ≈$0.

### B.2 — RESIDUAL WEAKNESSES (R-a / R-b NOW FIXED in Cycle 3; R-c / R-d remain)

- **R-a · High-qty AM lead time — FIXED (Cycle 3 R1, audited `outputs/audit-c3.md` Check 1).** Production now uses a finite **parallel machine-pool** model `ceil(qty·cycle_hr / (n_machines · machine_hours_per_day))` instead of one machine at 8 hr/day. **ECU `mjf @ q5000`: 744.1–1381.9 d → 49.7–92.3 d** (≈7–13 weeks); no costed process reads multi-year at automotive volume. The pool assumption is surfaced as an inspectable `lead_time.capacity` driver (e.g. `6 machines × 22 hr/day [DEFAULT]`) and is overridable → USER (`--set n_machines.MJF=20` → 18.9–35.1 d, unit cost unchanged). Verified live on the ECU mount + a second part (e46 ecu box plug).
- **R-b · Serial AM (FDM/SLA) +70% high — FIXED (Cycle 3 R2, audited `outputs/audit-c3.md` Check 2).** FDM/SLA now apply a legitimate **XY build-plate nesting** model: per-part single-nozzle/laser **deposition stays per-part**, but the shared **Z-axis plate sweep is amortized** over the XY nest count (`xy_packing_density × plate_area ÷ footprint`, DEFAULT 0.50, overridable → USER, shown as a `parts_per_build` driver). Re-run regression harness: **fdm median +0.75 → +0.38, sla +0.61 → +0.35** (both within the ±60% C2 bar); throttle `fdm $15.96 → $9.62 (−3%)`, `sla $25.00 → $14.82 (−17%)`, both in band. **Regression C2 flipped FAIL → PASS** (all five model guardrails green). This is not supplier-quote accuracy evidence. Deposition-dominated parts that nest 1–2/plate stay at the high edge — the honest, disclosed single-nozzle residual.
- **R-c · `parts_per_build` is a volumetric packing proxy** (`packing_density` 0.10), not a true orientation-aware bin-packer. Overridable per process; one real bureau quote collapses the band.
- **R-d · Absolute should-cost is characterized against INDEPENDENT LOCAL BANDS, not real supplier quotes.** 82% of (part, process, qty) estimates land in the independent band; CNC and IM are well-centered (100% in band); AM carries a size-dependent residual. Absolute $ is ±40-60% — now **measured per process** (see `accuracy-report.md`), not asserted. The single highest-leverage next step is 10-20 real supplier quotes on these exact parts.

**What V1 deliberately does NOT do (scope, not apology):** no supplier/live quotes (V2 — keeps CAD local), no CO₂, no curated regional cost *libraries* (one rate card + region vectors only), no metal-AM costing, no DB/PDF/frontend. The legacy toy `cost_per_cm3` stays untouched and never surfaced.

---

## C. THE EXACT QUESTIONS TO ASK THE ZOOX CONTACT

Ordered to extract the most decision-relevant signal. Lead with the CASTOR autopsy — he watched that company die and will have opinions.

**On CASTOR (the cautionary tale — what to avoid):**
1. "CASTOR led with *'which parts should we 3D-print?'* and died into the AM contraction. **What did they get right that we should keep**, and what was the strategic error — was it the additive-first framing, the business model, or the market timing?"
2. "We deliberately treat additive as *one branch* of make-vs-buy, usually the losing one at your volumes. Does a **process-agnostic, decision-first** framing actually map to how your team decides, or is that a vendor's fantasy?"
3. "CASTOR sold the *'batch-scan thousands of parts, flag the printable ones'* workflow to Siemens/Stanley. **Did that batch-triage motion create real value**, or was it a demo that didn't convert to recurring use?"

**On what he'd actually pay for (the wedge test):**
4. "If this tells a *design engineer*, at design time, **the make-vs-buy crossover quantity** with every cost driver visible and overridable — is that a tool you'd buy, or is that decision already owned by your cost-engineering team in aPriori?"
5. "We are **explicitly not** competing with aPriori on absolute should-cost accuracy or regional cost libraries. We compete on **speed, transparency, design-stage placement, and IP-locality (CAD never leaves the machine)**. Is that a real gap in your stack, or a nice-to-have?"
6. "We now ship a **measured** accuracy characterization (per-process error vs independent bands, ~82% in-band, CNC/IM centered, serial-AM flagged high) instead of a bare ±40-60%. Is provenance + live override + a published residual-error band enough to trust a number for a real sourcing decision, or do you still need a supplier-quote-validated band before it's usable?"
7. "**CAD never leaving the laptop** — is local-first / no-supplier-round-trip a hard procurement gate for Zoox IP (and would it be for the Saudi data-residency program), or table stakes everyone already clears?"

**On what's missing (the roadmap test):**
8. "We just closed our biggest cost-structure gaps — **AM build-plate nesting, CNC min-charge floors, region material-vs-labor splitting, and decision coherence**. The residuals we know about are **high-qty AM lead-time (single-machine assumption)** and **serial-AM running high vs a volumetric reference**. Which of *those* is the dealbreaker for you, and what did I not list?"
9. "Our cycle times and packing density are geometry-derived estimates the buyer overrides. **Is per-driver override the right answer to 'your cycle times are wrong,'** or do you need them right out of the box — and if so, from a library or from your own historical shop data?"
10. "What's the **one number on this card** that, if it were credible, would change a real decision for you next quarter — cost, lead time, the crossover quantity, or the make-vs-buy direction?"

---

## D. Evidence appendix (what I actually ran)

- **Coherence (live):** ECU mount q50/5000 → headline **mjf $44.13** ≡ `@ qty 50` reco **mjf $44.13** ≡ DFM-ready argmin (cnc_3axis $43.60 correctly excluded — undercuts). Throttle q100/10000 → headline **mjf $7.25** ≡ reco **mjf**. `test_g4_decision_coherence_across_parts` loops the set and asserts equality + DFM-ready — passes.
- **Independent geometry/cost re-derivation (raw trimesh, bypassing the engine):** ECU SLS unit cost reproduced to the cent — `n=16, machine $37.50, material $4.45, labor $3.89, setup $1.40 → $47.25`. The MEASURED drivers are real, not fabricated.
- **Regression harness (local, independent, zero network):** the captured external geometry-only run covers 202 comparisons; reproduce it only with a license-reviewed corpus via `python -m src.costing.harness --real-parts-dir <licensed-corpus>`. Protected CI runs deterministic, internally authored coupons with no private assets; `test_harness_is_deterministic` passes. Neither suite is supplier-quote ground truth. Production accuracy remains blocked until `python -m src.costing.harness --require-production-evidence` passes the 20+ part provenance-locked supplier holdout thresholds. Reports: `outputs/accuracy-report.md` (external historical geometry benchmark) and `outputs/calibration-report.md` (CI regression).
- **Invariants/IP:** `assert_sums()` enforces Σ=unit (incl. the min-charge-floor line — verified throttle q1 Σ=$90.00); `grep cost_factor src/costing/` → none (toy model unsurfaced); G7 + harness socket-block tests pass (zero network).
- **Gate suite:** `pytest tests/test_costing_model.py tests/test_costing_gates.py tests/test_costing_accuracy.py` → **36 passed in 413.91s**.

**Key file paths:**
- Costing package: `backend/src/costing/` (cost_model.py, decision.py, rates.py, drivers.py, estimate.py, leadtime.py, report.py, cli.py, harness.py)
- Tests: `backend/tests/{test_costing_model.py, test_costing_gates.py, test_costing_accuracy.py}`
- Spec / notes / accuracy / audit: `outputs/{v1-fix-spec.md, v1-build-notes.md, accuracy-report.md, audit-v1.md}`

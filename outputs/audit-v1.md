# CadVerify V1 — Validation Audit (Validation-Auditor, Cycle 2)

**Author:** Validation-Auditor agent · **Date:** 2026-06-28 · **Verdict: COMPLETE — the 8 weaknesses are genuinely closed; ship V1.**
**Audience to defend against:** Zoox Head of Manufacturing (runs aPriori-class tooling; knows real cycle times, powder-bed nesting, and automotive volumes; will catch a fabricated number or an incoherent decision sentence in seconds).

**What I did (ran it myself, did not trust the build notes):**
- Ran the V1 CLI live on the ECU Firewall Mount (q50/5000), Throttle Body Adapter (q100/10000), the broken MAF adapter, plus `--region CN`, `--cavities 4 --complexity complex`, and `--qty 1`.
- Re-derived the ECU SLS unit cost independently from raw `trimesh` geometry + the stated DEFAULTs (bypassing the engine) — reproduced **$47.25 to the cent**.
- Opened every costing module (rates, drivers, cost_model, decision, estimate, report, cli) + the new `harness.py` and read the decision-coherence logic line by line.
- Ran the full gate suite: **`36 passed in 413.91s`** (V0 = 17; +9 model/gate fixes for the 8 weaknesses, +10 accuracy-harness tests).
- Scanned for network egress and confirmed the legacy toy cost model is never surfaced as a dollar.

**Headline:** the V0 decision-sentence incoherence (the top-priority bug) is gone — on every real part the headline make-now process is computed from the *same single ranking* as the low-qty recommendation, so they cannot disagree by construction. All 8 weaknesses move from "stated soft spot" to "fixed and traceable." The absolute-$ accuracy is now **measured** (not "trust us ±40-60%"), and the accuracy report is honest that it is a MIXED result against independent local bands, not a claim of absolute truth.

---

## 0. Audit result at a glance

| # | Check | What I tested | Result |
|---|---|---|---|
| 1 | **Coherence (#7)** | On ≥2 real parts, headline make-now == low-qty argmin recommendation? | **PASS** |
| 2 | **Weakness closure** | Walk all 8 — fixed with evidence from real output, or open? | **PASS — 8/8 fixed** |
| 3 | **No regression + invariants** | Σ(lines)=unit, provenance on every driver, G1 refuses MAF, tests pass, toy model unsurfaced | **PASS** |
| 4 | **Numbers defensible** | Spot-check 2 parts vs independent math; nested-AM + floors in a sane band | **PASS** |
| 5 | **Accuracy-report integrity** | Method independent/non-circular and honest about residual error? | **PASS (honest MIXED)** |
| 6 | **CAD-as-IP** | Zero network egress incl. the accuracy harness | **PASS** |

**No coherence bug remains. No invariant broke. No number is fabricated or unexplainable. The accuracy report is not circular and is honest about its residuals.** → **COMPLETE.**

---

## CHECK 1 — COHERENCE (#7), the top-priority bug — PASS

**Root cause in V0:** headline make = argmin *fixed* (fdm), crossover-buy = argmin *variable* (injection_molding, DFM-fail), low-qty reco = argmin *unit* (cnc_3axis, DFM-fail) — three different processes side by side.

**V1 fix verified live.** `decision.py::make_vs_buy` computes one ranking, `make_ready_ranked(q)` = DFM-ready ADDITIVE∪SUBTRACTIVE sorted by real unit cost. `make_now = make_ready_ranked(q_lo)[0]` and `recommendation[q] = make_ready_ranked(q)[0]` are drawn from the *same* function — structurally cannot diverge.

**ECU Firewall Mount, q50/5000 (real CLI output):**
- Headline: `Make by mjf (PP) — $44.13/unit at qty 50, the cheapest make-as-is option and your low-volume pick.`
- `@ qty 50 → mjf / PP ($44.13/unit) (make-as-is, recommended)`
- argmin over DFM-ready make at q50: **mjf $44.13** < sls $47.25 < fdm $57.24 < cnc_5axis $61.56 < dlp $125.08 < sla $146.81. (cnc_3axis $43.60 is cheaper but **excluded** — 424 undercut faces, DFM-fail.)
- → headline **mjf** ≡ reco **mjf** ≡ argmin **mjf**. **One process, three places, identical.** V0 contradiction gone.

**Throttle Body Adapter, q100/10000 (real CLI output):**
- Headline `Make by mjf — $7.25/unit at qty 100` ≡ `@ qty 100 → mjf $7.25/unit (make-as-is, recommended)` ≡ argmin DFM-ready make (mjf $7.25 < sls $7.42 < dlp $12.73 < cnc_turning $14.93 < fdm $15.96). Coherent. (V0 here was headline fdm ≠ reco cnc_turning — also gone.)

**Procedural proof:** `test_g4_decision_coherence_across_parts` loops the real-parts set and asserts `make_now_process == recommendation[q_lo].process` AND that process is `dfm_ready` for every OK part — **passes** (≥5 parts checked, like G1).

**Crossover semantics are now consistent and conditional.** The headline names a crossover to injection_molding ("above ~739 units IM is cheaper") but immediately labels it: *"injection_molding requires design-for-molding — the part currently FAILS draft DFM (564 sidewall faces ... below 1.0° draft); the tooling cost shown is 'if redesigned for molding', not a current-capability quote."* The per-qty tiers reinforce it: at q5000 the tier-1 reco is still the DFM-ready make-as-is **mjf $43.98**, with IM appearing only as tier-2 "cheaper if redesigned ← crossover." This is the #6 fix working: the buy route is presented as a conditional, never asserted as current capability.

---

## CHECK 2 — WEAKNESS CLOSURE (all 8) — PASS

| # | Weakness | Evidence from real V1 output | Status |
|---|---|---|---|
| 1 | Small-part AM over-cost (flat $17.50 post-labor) | Throttle SLS **$41.15 → $7.42**, MJF $40.29 → $7.25. Post-labor split: `finish 0.08hr/part + bulk 0.5hr/build ÷ 145 = 0.083hr × $35`. | **FIXED** |
| 2 | AM = single isolated build (machine 82% of unit) | ECU SLS machine **$103.82 → $37.50** (`build-job 600mm÷20 = 30hr ÷ 16 parts/build`); throttle SLS machine **$4.14** (÷145). FDM/SLA stay serial (honest per-part, stated in `source`). | **FIXED** |
| 3 | No min-charge / lot floor | Throttle cnc_turning **q1 → $90.00**, `min_charge_floor $57.74` booked as its own line item, Σ = $90.00 holds. Negligible at volume. | **FIXED** |
| 4 | One flat region scalar on everything | `--region CN` ECU SLS: **material ×0.98** (commodity, not labor-scaled), machine/labor/setup **×0.55**, tooling **×0.45**; `region_split` driver tagged USER. The "CN ×0.65 on a resin PO" bug is gone. | **FIXED** |
| 5 | Tooling = 4-bucket step on bbox only | `--cavities 4 --complexity complex` ECU IM: **tooling $118,755.71** (`30000 × 4^0.7 (=2.64) × complex (=1.50)`), per-part machine **÷4 = $0.38**. DEFAULT 1-cav moderate = **$30,000 (= V0, no silent change)**. | **FIXED** |
| 6 | DFM-fail process headlined | Headline drawn only from DFM-ready make (mjf). IM shown as tier-2 "cheaper if redesigned (add draft, tooling-dominated)" + explicit FAILS-draft Note. Never asserted as current capability. | **FIXED** |
| 7 | Decision incoherence | See Check 1 — headline ≡ low-qty argmin ≡ DFM-ready make champion, single-sourced. | **FIXED** |
| 8 | One setup over the whole lot | Setup recurs `ceil(qty/lot_size)`: ECU cnc_3axis q50 → 1 setup, q5000 → 50 setups (`$0.0053 → $0.2625/unit`); AM lot = one build (`ceil(50/9)=6 setups` for ECU mjf). | **FIXED** |

`weaknessesFixed` = all 8.

---

## CHECK 3 — NO REGRESSION + INVARIANTS — PASS

- **Σ(line_items) == unit_cost.** `cost_model.py::cost_breakdown` calls `est.assert_sums()` before returning; every CLI card prints `line items Σ = $X (= ...)`. The min-charge floor is booked as its own `min_charge_floor` line item, so the invariant holds even when the clamp bites (verified live: throttle q1 Σ = $90.00 = 17.50+0.14+4.11+10.50+57.74). G3 test passes.
- **Provenance on every driver.** New drivers — `parts_per_build`, `region_split`, `min_charge_floor`, cavity/complexity in `tooling_cost.source`, nesting in `machine_cost.source`, per-lot in `setup_cost.source` — all carry non-empty `source` + a Provenance tag. DEFAULTs flip to USER when overridden (`--region CN` → region_split USER; `--cavities 4` → n_cavities USER, verified). G3 asserts source+provenance on every driver.
- **G1 still refuses the broken MAF part.** Live: `Geometry: 0 cm³ ... watertight ✗ → GEOMETRY INVALID — repair required. No cost produced.` Zero estimates, no decision. `test_g1_*` passes; the engine's raw `sls pass` still shows underneath — the cost layer refuses to monetize it.
- **Tests.** `36 passed in 413.91s` (V0 was 17). Breakdown: test_costing_model.py (procedural, 12) + test_costing_gates.py (real-part gates, 14) + test_costing_accuracy.py (harness, 10). No skips with the parts dir present.
- **Legacy toy `cost_per_cm3` never surfaced.** `_estimate_cost_factor` lives in `matcher/profile_matcher.py` and is stored on `ProcessScore.estimated_cost_factor` for DFM ranking only. `grep cost_factor src/costing/` returns nothing but a comment in `__init__.py` stating it is never surfaced. Every dollar in the card comes from `cost_breakdown`'s line items; the feasibility line shows DFM scores (0-1), never a toy dollar.

---

## CHECK 4 — NUMBERS STILL DEFENSIBLE — PASS

**Spot-check A — ECU SLS, independent re-derivation from raw `trimesh` (bypassing the engine):**
```
V=66.79cm3  bbox=32.6×62.0×160.0mm
nesting: n = int(0.10 × (340·340·600/1000) / ((32.6+5)(62+5)(160+5)/1000)) = 16
machine = (600/20)/16 × $20  = $37.50
material= 66.79×1.01/1000×60×1.10 = $4.45
labor   = (0.08+0.5/16)×35 = $3.89 ;  setup = 0.5×35×ceil(50/16)/50 = $1.40
unit    = $47.25   ← reproduces the CLI to the cent
```
Every figure traces to a MEASURED driver × a stated DEFAULT. Nothing fabricated.

**Spot-check B — Throttle SLS @ q100 = $7.42.** Independent volumetric powder-bed band (R1, $0.25-1.50/cm³ + $4-18 handling on 2.81 cm³) = **$4.70-$22.22** → in band. V0's $41.15 (over-cost) is gone; the now-nested figure lands in the independent ballpark.

**Floors & tooling in sane bands:** min-charge $90 = a real CNC shop minimum; ECU IM tooling $30,000 (160 mm, 1-cavity) ∈ independent $25-70k tier band; throttle IM tooling $6,000 (40 mm) ∈ $1.5-8k band. No estimate sinks below its process's real shop floor.

---

## CHECK 5 — ACCURACY-REPORT INTEGRITY — PASS (honest MIXED, not a rubber stamp)

**Independence (non-circular):**
- **R1 (AM)** is genuinely orthogonal: a pure `handling_floor + V_cm³ × rate_$cm³` service-bureau model that **never looks at** V1's cycle time, machine rate, or parts-per-build. V1 builds AM cost bottom-up (cycle-time × $/hr ÷ nesting). Agreement is real corroboration of the nesting fix, not a restatement.
- **R3 (IM)** is orthogonal: tool-$ bands by size×cavity with **different numbers** than V1's tier table (V1 tier L $30k vs R3 150-300 mm band $25-70k); V1 lands inside.
- **R2 (CNC)** is *semi*-independent: same material-removal physics family as V1's `_cnc_cycle` but deliberately different banded constants (MRR 40 vs V1's 50, rate $60-120 vs V1's fixed 65/75/110, adds a per-part handling term V1 lacks, plus a shop-min). The report does **not** overclaim it as orthogonal ground truth — it explicitly says these are "an independent cross-check, **not** a claim of absolute should-cost truth: that requires real supplier quotes." This is the honest framing.

**Honesty about residual error:**
- Overall verdict is stated **MIXED**, not PASS. Criterion **C2 is marked FAIL** in the report's own acceptance table (fdm median +0.75 > 0.60). The report does not bury this.
- The residual is *explained, not papered over*: serial AM (FDM/SLA) is deliberately not nested (single nozzle / laser trace is genuinely per-part — a stated V1 design choice), so it runs systematically high vs a volumetric bureau reference. The size-dependent AM curvature (under-costs tiny parts, over-costs medium/large) is named as the real headline finding.
- The test suite is honest in the same direction: `test_serial_am_residual_high_bias_is_measured` asserts FDM/SLA run **high** (measures the flag); `test_non_serial_processes_within_band_excluding_serial_am` excludes serial AM from the ±60% bar rather than forcing a pass. No test asserts C2 passes.
- The deviation from fix-spec §13.1 (changing R1 from `max(order_min, V×rate)` to `handling + V×rate`) is disclosed with rationale (per-order min is not a per-unit floor at q100+) and the line "neither is tuned to make V1 pass."

**Reproducibility:** the report's per-part numbers match my fresh CLI runs to the cent (throttle sls $7.42, mjf $7.25, cnc_turning $14.93). `test_harness_is_deterministic` passes (two runs identical). Not fabricated.

**Verdict:** independent enough (R1/R3 orthogonal, R2 disclosed as semi-independent), honest about its MIXED result and residuals, points to real supplier quotes as the path to true ground-truth validation. Not circular, not dishonest.

---

## CHECK 6 — CAD-as-IP (zero network egress) — PASS

- `grep` for socket/requests/urllib/httpx/boto/api_key over `src/costing/` returns only doc-comment false positives. Non-stdlib imports are `src.analysis`, `src.profiles`, `src.matcher` (the local engine) only.
- `test_g7_no_outbound_socket_during_costing` replaces `socket.socket` with a raising stub during costing → still `status=OK`.
- `test_zero_network_egress_during_harness` wraps the accuracy harness in the same socket block → runs, produces comparisons, opens **zero** sockets.
- Every CLI run logs `IP-local, zero network calls`. The accuracy harness uses local price BANDS encoded as constants — no live API calls.

---

## Residual weaknesses that remain (honest — carried into V1's packet)

These are **not** regressions and **not** in the 8-fix scope; state them proactively to the buyer:

- **R-a · Lead time at high-qty AM is large** (e.g. mjf q5000 ≈ 744-1382 days) because production days assume a **single serial machine** at 8 hr/day. Nesting correctly *shrinks per-part production* vs V0, but a multi-machine / parallel-build lead-time model is a future refinement (build-notes §residuals). The cost decision is unaffected; the lead-time *days* at extreme qty are pessimistic.
- **R-b · Serial-AM (FDM/SLA) runs ~+70% high vs a volumetric bureau reference** — measured and reported, by design (no nesting for serial deposition). It is the documented accuracy FLAG, not a hidden error.
- **R-c · `parts_per_build` is a volumetric packing proxy** (packing_density 0.10), not a true orientation-aware bin-packer. Overridable via `--set packing_density.SLS=…`; the path to tighten is one real bureau quote.
- **R-d · Absolute should-cost is characterized against independent local BANDS, not real supplier quotes.** V1 stands behind the decision (crossover + make-vs-buy direction); absolute $ is ±40-60%, now *measured per process* rather than asserted.

---

## Evidence appendix (what I actually ran)

- `python -m src.costing.cli <ECU> --qty 50,5000` → coherent mjf headline == reco; full itemized cards with Σ checks.
- `... <ThrottleBodyAdapter> --qty 100,10000` → coherent mjf headline == reco; small-part AM in band.
- `... <MAF> ` → GEOMETRY_INVALID, zero estimates (G1 intact).
- `... <ECU> --qty 1` → cnc_turning $90.00 with `min_charge_floor` line (#3).
- `... <ECU> --region CN` → material ×0.98 vs labor ×0.55 (#4).
- `... <ECU> --cavities 4 --complexity complex` → IM tooling $118,756, machine ÷4 (#5).
- Independent `trimesh` re-derivation of ECU SLS → **$47.25** exact.
- `pytest tests/test_costing_model.py tests/test_costing_gates.py tests/test_costing_accuracy.py -q` → **36 passed in 413.91s**.
- IP scan + `grep cost_factor src/costing/` → clean (toy model never surfaced; no network primitives).

**Key paths:** costing package `/Users/nazeem/Desktop/developer/cadverify/backend/src/costing/` (cost_model.py, decision.py, rates.py, drivers.py, estimate.py, report.py, cli.py, harness.py); tests `/Users/nazeem/Desktop/developer/cadverify/backend/tests/{test_costing_model.py,test_costing_gates.py,test_costing_accuracy.py}`; accuracy report `/Users/nazeem/Desktop/developer/cadverify/outputs/accuracy-report.md`.

# CadVerify — Cycle 1 Strategy

**Author:** Strategist agent · **Date:** 2026-06-28 · **Status:** LOCKED for Cycle 1
**Scope:** (1) the named wedge, (2) the LOCKED cost-data source-of-truth decision, (3) the V0 demo-credibility bar.

---

## 0. Ground truth — what the engine actually is today (verified firsthand, not inherited)

I re-ran the canonical sequence on the repo's real automotive STL parts. Confirmed:

| Part | Observed engine output | Why a buyer rejects it |
|---|---|---|
| MAF Sensor Adapter (`655044_…MAF_Sensor_Adapter…`) | `volume=0 mm³`, `watertight=False`, yet **`sls score=1.00 pass`, cost_factor=0.2**; also recommends `cnc_turning` in **Inconel 718** | Broken geometry → confident PASS + a fabricated cost. Volume silently floored to 1 cm³. Credibility dies in 10 seconds. |
| ECU Firewall Mount (plastic bracket, 160×62×33 mm) | Top picks SLS/MJF in nylon; **`cnc_turning` in Inconel 718` at score 1.00** ranked #3 | Turning is for rotational parts; this is a flat bracket. Inconel-718 is an aerospace superalloy on a commodity plastic part. Naive process×material matching. |
| Macchina M2 case | `sla/dlp` ranked above conventional options | Plausible at qty=1, absurd at automotive volume — there is **no quantity, no setup, no tooling amortization** in the model. |

**The cost model is a toy:** `estimated_cost_factor = cost_per_cm³[process] × max(volume_cm³, 1.0)` — dimensionless. No dollars, no lead time, no quantity, no setup/labor/region, no make-vs-buy.

**What scaffolding already exists** (matters for the cost decision below):
- `MaterialProfile.cost_per_kg` (USD/kg, "approximate") **exists** for every material, plus density → we can compute **material mass = measured CAD volume × density**, a *measured* driver, not a guess.
- `MachineProfile` has **no hourly rate / no cost field** — there is zero machine-time cost basis today.
- `PrintProfile.estimated_time_hours` / `estimated_cost_usd` are dataclass fields that exist but are **unused** — nothing populates them; the live path returns only the dimensionless factor.

So: the bones for an honest material-cost line exist; everything else (machine rate, cycle time, setup, labor, region, lot size) is missing and must be made **explicit and inspectable**, never hard-coded and dressed as real.

---

## 1. The Wedge — precisely

> **CadVerify turns a CAD file into a manufacturing *decision* — process recommendation, an explainable should-cost, a lead-time range, and a quantity-aware make-vs-buy call — in seconds, locally, with every cost driver visible and overridable. It is process-agnostic (15+ AM and conventional methods), design-engineer-facing, and glass-box: the buyer can see and change every assumption behind every number, because the rates that drive it are the buyer's own.**

The headline deliverable is the **decision** (make-vs-buy + quantity crossover), not the DFM check. DFM and process scoring are table stakes; the wedge is putting a *defensible, transparent economic decision* in a design engineer's hands at design time.

### Who we are NOT, and why

**We are NOT CASTOR (additive-first — the grave).**
CASTOR started from "which parts should we 3D-print?" Its TAM was bolted to AM adoption, and it died into the 2023 AM-market contraction owing ~$2.3M despite Siemens Energy / Stanley Black & Decker / Evonik logos and Xerox money. We do **not** start from additive. AM is *one branch* of the make-vs-buy tree — and at automotive/AV volumes it is usually the *losing* branch. Treating "should we print this?" as the question is the strategic error that killed CASTOR. Our question is "what is the cheapest *credible* way to make this part at *your* quantity?" — and the honest answer is frequently casting, molding, or machining.

**We are NOT aPriori (heavyweight, opaque, cost-engineer-oriented).**
aPriori's moat is real and unreplicable on our budget: 20 years of digital factories, physics-based process models, and **92+ regional cost libraries**, with machine-level routing across 440+ methods. But it is heavy, training-intensive, sold to *cost engineers* (not the design engineer who creates the cost), and its inferred routing frequently needs manual override — an authoritative *black box*. We will **not** try to out-library aPriori, and we will **not** rebuild the toy `cost_per_cm³` model at higher fidelity and call it real — that is the exact fabrication the constraints forbid, and an aPriori-trained engineer would shred it (wrong regional rates, wrong cycle times, no provenance). We compete on a *different axis*: speed, transparency, design-stage placement, control, and IP-locality.

**We ARE in 3D Spark's lane (the survivor) — but differentiated.**
3D Spark (Hamburg, alive: Deutsche Bahn et al.) is the model: a standardized per-part scorecard — feasibility, cost, lead time, CO₂, make-or-buy — across 15+ AM *and conventional* technologies, design-engineer/procurement-facing. That is the proven-survivable shape and we adopt it. Our differentiation vs 3D Spark:
1. **Glass-box, buyer-driven cost.** 3D Spark leans on integrated cost profiles + real-time *supplier pricing*. Ours is a parametric should-cost driven by the **buyer's own shop rates**, with **per-driver provenance** (every line tagged MEASURED / USER / DEFAULT) and full override. We win on *explainability and control*, not library depth.
2. **Local-first / CAD-as-IP.** The part never leaves the machine — no supplier round-trip, no third-party exfiltration. For automotive/AV/defense IP (Zoox; and this program's Saudi data-residency requirement), that is a hard procurement gate 3D Spark's supplier-pricing model does not natively clear.
3. **Decision-first framing.** Make-vs-buy + quantity crossover is the *headline*, not a feature buried under quoting.

---

## 2. Cost-Data Source of Truth — the LOCKED decision

### The three options, judged

**(a) Driver-level cost libraries we build/license** (machine/material/regional rates — aPriori's moat).
- *Build it ourselves badly* → a worse aPriori: a black box whose absolute numbers an aPriori-trained engineer dismantles on sight (stale rates, wrong cycle-time physics, no provenance). *License it* → expensive, a business-dev **GATE**, and **not demoable now**. Verdict: **V1+ trajectory, not V0.** It is also strategically wrong to lead with: it puts us head-to-head with aPriori on aPriori's terms.

**(b) User-supplied shop rates + explicit, traceable driver assumptions** (lighter, "explain the number").
- Honest, demoable *today*, no licensing, design-engineer-friendly. The number is **"correct given these inputs," and the inputs are the buyer's own.** Verdict: **PICK for V0.**

**(c) Supplier-quote integration** (3D Spark's path).
- Requires a pre-onboarded supplier network, real-time pricing feeds, and — fatally for a demo — **sending the CAD to third parties**, which violates the CAD-as-IP constraint and cannot be stood up on this machine now. Verdict: **V2 partnership play, GATED on supplier relationships.** Best positioned later as *optional validation* of the should-cost, never as the source of truth.

### LOCKED DECISION: **(b) — user-supplied shop rates + explicit, traceable driver assumptions, for V0.**

**The cost model is parametric and fully itemized:**

```
cost_per_part(qty) =
      [ setup_time·labor_rate + tooling_cost ] / qty        ← FIXED, amortized over lot
    + part_mass · material_$/kg · (1 + scrap_factor)        ← MATERIAL
    + cycle_time · machine_rate                              ← MACHINE
    + post_process_time · labor_rate                         ← LABOR / FINISH
    )  × region_multiplier × (1 + margin)
where  part_mass = measured_CAD_volume × material_density
```

**Every driver carries a provenance tag — this tagging *is* the product:**
- **MEASURED** — extracted from the CAD (volume → mass; bounding box; removed-volume / build-height proxies for cycle time). Not assumable.
- **USER** — the buyer's own number (their machine rate, labor rate, material PO price, lot size). Authoritative.
- **DEFAULT** — our *stated, flagged* assumption used only when the user supplies nothing (e.g., a regional default rate). Always visible, always overridable, never silent.

### Why this survives an aPriori-trained cost engineer

The skeptic's strongest punch is: *"Your geometry-derived cycle times are wrong, so your absolute dollars are wrong."* **Correct — and we say so first.** Two structural answers:

1. **We make a different, honest claim than aPriori.** We do **not** claim should-cost-grade *absolute* accuracy in V0. Claiming it would be the fabrication the constraints forbid. We claim a **transparent, parametric, buyer-driven estimate** in which every driver is inspectable and overridable, with a **stated error band** on each estimated driver. The aPriori engineer's core complaint about any tool — *"where did this number come from?"* — is exactly what provenance + override defuses. A cycle-time estimate they distrust is one field they edit to their real value; the model recomputes live.

2. **The decision is robust even when the absolute dollars are not.** Make-vs-buy and the quantity crossover depend on the **shape** of the cost curve — the split between amortized fixed cost (setup + tooling) and per-unit variable cost — and that shape is driven by the **buyer's own rates**, not our cycle-time guess to three significant figures. So even at ±X% absolute error, the **crossover quantity** and the **make-vs-buy direction** stay decision-credible. We lead with the conclusion that is *structurally* defensible, and we are honest about the precision of the inputs that are not.

This is *complementary* to aPriori, not a frontal assault: speed + transparency + design-stage + control + IP-local, with explicit error bands — a different promise that an aPriori user has no existing tool for.

### V1 → V2 trajectory (do not build now, but the path is named)
- **V1:** add a *curated default-rate library* (an (a)-lite layer) so a user who supplies nothing still gets a **bracketed** estimate with stated regional defaults — moving toward (a) while *always* preserving override + provenance. Add a validation harness vs ground-truth anchors with documented error bands.
- **V2:** optional **(c)** supplier-quote integration as a *"validate the should-cost against a real quote"* feature (opt-in, IP-gated) — suppliers validate, they never become the silent source of truth.

---

## 3. V0 Demo-Credibility Bar — concrete and testable

Audience: the **Zoox Head of Manufacturing** — runs aPriori-class tooling, knows real cycle times, knows automotive volumes, and will catch a fabricated number instantly. V0 is **demo-credible** only if **all** of the following pass on the repo's real parts. Each is a pass/fail gate.

**G1 — No-lies / robustness gate (the credibility killer).**
Run all 107 real parts. **Zero** parts with `volume ≤ 0` or `watertight = False` may return a numeric cost or a confident PASS. The MAF Sensor Adapter must return **"geometry invalid — repair required,"** not `sls pass cost=0.2`.
*Test:* assert no part with non-positive volume or non-watertight mesh yields a numeric cost or `verdict=pass` without a blocking flag. **Must be 100%.**

**G2 — Sane-routing gate.**
No physically absurd process×material recommendation in the top results. The plastic ECU Firewall Mount must **not** surface CNC-turning or any superalloy (Inconel/Ti) as a recommended option.
*Test:* on a labeled subset, assert (i) turning is offered only for parts with a dominant rotational axis, and (ii) superalloys are never recommended for commodity-polymer brackets. **Zero violations.**

**G3 — Explainable-cost gate.**
For a chosen real part (ECU Firewall Mount), V0 emits a **dollar** figure with **every** driver itemized — material mass (MEASURED), material $/kg, machine rate, cycle-time estimate **and its formula**, setup, labor, region, lot size — each tagged MEASURED/USER/DEFAULT, and the line items **sum to the total**. Editing any one input updates the total correctly and monotonically.
*Test:* breakdown present; provenance on every line; Σ(lines) = total; perturb one rate → total moves in the correct direction.

**G4 — Decision-layer gate (the wedge itself).**
For that part at **two quantities (e.g., 50 vs 5,000)**, V0 outputs (i) a **make-vs-buy direction** and (ii) a **quantity crossover** where a low-fixed/high-variable process (CNC/AM) loses to a high-fixed/low-variable one (injection molding / casting) — the crossover derived from the **visible** fixed-vs-variable structure and driven by the buyer's rates.
*Test:* crossover quantity computed and displayed; raising the buyer's tooling cost moves the crossover in the correct direction (sensitivity is monotonic and explainable).

**G5 — Lead-time gate.**
A lead-time **range** per process with **stated components** (queue + setup + cycle×qty + post-process + ship), explicitly labeled an estimate with assumptions — **never** a fake precise date. It must scale with quantity.
*Test:* range present with component breakdown; lead time increases with quantity.

**G6 — Honesty / error-band gate.**
Every number carries its assumption set, and each estimated driver carries a **stated error band**. At least **one** ground-truth anchor (a known supplier quote or a published rate) is documented with the resulting error shown. **No naked numbers.**
*Test:* assumptions panel present on every figure; ≥1 validation anchor documented with its error band.

**G7 — Speed + IP-locality gate (positioning made literal).**
The demo part goes **CAD → decision in seconds**, fully **local** — the CAD never leaves the machine, **zero** network egress during analysis.
*Test:* wall-clock from upload to decision < ~10 s on the demo part; no outbound network calls during analysis.

**Demo-credible ≡ G1–G7 all green on the repo's real automotive parts.** Anything less is a toy with a nicer UI, and the buyer will know.

---

## Acceptance self-check
- **Survives an aPriori skeptic?** Yes — we explicitly decline the absolute-accuracy fight, lead with the structurally-robust decision, expose and let them override every driver, and state error bands. Provenance + override is the answer to "where did this number come from?"
- **Survives the CASTOR lesson?** Yes — process-agnostic, additive is one branch and usually the losing one at volume; TAM is not bolted to AM adoption.
- **V0 bar concrete and testable?** Yes — G1–G7 are pass/fail assertions on the repo's 107 real parts.
- **No fabricated cost dressed as real?** Yes — (b) makes the inputs the buyer's, tags provenance, and forbids silent defaults.

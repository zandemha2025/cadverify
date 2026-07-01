# CadVerify — Platform Experience (core flow, built)

**Role:** Platform-Experience Designer.
**Job:** get an engineer to a defensible manufacturing decision fast, against the cost-truth engine's REAL outputs, with every assumption visible + editable and role-aware views. Build real screens, not prose.
**Date:** 2026-06-29.
**Acceptance bar (self-audited §6):** a manufacturing engineer reaches a trustworthy decision fast + can see/edit every assumption; routing correctness + confidence are legible; built on the real engine outputs (not the toy `cost_per_cm3`); role-views present; `npm run build` green.

---

## 0. What this delivery is

The glass-box component library (`src/components/glass-box/*`) and the design-system showcase already existed at the 2026 bar — but they were **only rendered in the `/design-system` showcase**. The live upload→decision workspace still ran the old `Analyze · Cost · Tolerances · Share` tabs and never touched a single glass-box component, the Role Lens, routing, confidence, or calibration.

**This delivery wires the glass box into the live product.** The part-as-object workspace is rebuilt as the **role-gated glass-box over one analysis object** described in `ia-and-flows.md`: one upload → one `report_to_dict` → five lenses (tabs), the Role Lens sets the landing tab, the part stays in a persistent 3D rail, and per-shop calibration is an always-on topbar fact. Every number is bound to the engine's real fields.

Routes that exercise it: **`/cost`** (lands Design lens · Decision), **`/analyze`** (lands Mfg lens · Routing & DFM), the **`/`** marketing demo embed, and the **`/design-system`** build-proof showcase.

---

## 1. Screens built (files + engine bindings)

All paths under `frontend/src/`.

### 1.1 The workspace shell — role-aware, one object, five lenses
`components/workspace/PartWorkspace.tsx` (rebuilt)

- **Topbar:** part name · **`CalibrationBar`** ("Calibrated to <shop> ▾" / honest "Not calibrated — generic defaults") · **`RoleLens`** selector · New part.
- **Role Lens → landing tab** (`LANDS_TO_TAB`): Design→Decision, Cost→Glass Box, Sourcing→Compare, Mfg→Routing & DFM, Buyer→Decision (+ trust panel). Switching the lens re-lands you; **walls nothing off** — all five tabs stay one click away (multi-hat reality).
- **Tabs:** `Decision · Glass Box · Routing & DFM · Compare · Share`.
- **Persistent 3D rail** (`CadViewer`) shared across every lens, with the MEASURED geometry facts (vol · bbox · faces · watertight) under it and the two-way face↔blocker highlight live on the Routing lens.
- **Binds:** the whole `report_to_dict` (`CostReport`) + the DFM `ValidationResult`; calibration parsed from `assumptions` provenance + the engine's calibration `note`.

### 1.2 DECISION lens — the decision, not the dollar (Design + Buyer)
`components/cost/CostDecisionView.tsx` (elevated)

- Hero `DecisionHeadline` (make-vs-buy verdict + DFM-ready badge + crossover sentence) over three `NumberReadout`s; the **cost readout carries its confidence band** beneath (never fake-exact).
- **`RedesignBanner`** fires when `decision.tooling_dfm_ready === false` — the crossover is real but the tooling route is conditional ("if redesigned," not a current quote), linked to Routing & DFM.
- The signature **quantity slider** live-flips the recommended process at the crossover (client-side, from the report's own fitted curves — instant) + the **breakeven chart**.
- **"View glass box"** drills the answer into its drivers (jumps to the Glass Box lens — universal drill-down). **"Adjust inputs & re-cost"** is the server tweak-rerun loop.
- **"Why trust this"** panel (open by default for the Buyer lens): method · the engine's verbatim confidence honesty · IP-local / zero-egress signal.
- **Binds:** `decision.{make_now_process, crossover_qty, tooling_process, tooling_dfm_ready, note}` · `estimates[].{confidence, lead_time, dfm_blockers}` · fitted curves from real unit costs.

### 1.3 GLASS BOX lens — the open model (Cost eng)
`components/workspace/GlassBoxView.tsx` (new)

- Process × quantity selectors → `DriverBreakdown` for that estimate: every driver provenance-tagged + sourced, **drill inline** to the engine's verbatim source string, with the **Σ line-items = unit-cost** coherence row always shown (no naked numbers).
- `ConfidenceInterval` (band + the verbatim "assumption-based, not yet validated" honesty label) and `AssumptionGrid` — **every assumption inline-editable; override re-tags `USER`**. `ProvenanceLegend` + Save-as-scenario.
- **Binds:** `estimates[].{drivers[], line_items, confidence}` · `assumptions[]`.

### 1.4 ROUTING & DFM lens — is it made the right way (Mfg eng)
`components/workspace/RoutingDfmView.tsx` (new)

- `RoutingCard` foregrounds the engine's **reasoning paragraph** (this persona's trust object) over the MEASURED drivers that decided the archetype/process.
- `DfmMatrix` across all processes — verdict + score + the geometry-linked blocker; **click a blocker → faces light up in the 3D rail** (two-way). `costed=false` rows honestly de-weighted. The full per-process `AnalysisDashboard` sits below for the deep audit.
- **Binds:** `routing.{archetype, recommended_process, confidence, reasoning, alternatives, drivers}` · `engine_feasibility[]` · `estimates[].dfm_blockers` · the DFM `ValidationResult`.

### 1.5 COMPARE lens — the decision board (Sourcing)
`components/workspace/CompareView.tsx` (new)

- `ProcessComparison` built from the **real per-process estimates**: each process priced at both costed quantities (the volume break — the crossover made tabular), every cell a **banded** real number, each drillable into its glass box. The crossover chart as centrepiece, the make/buy flip surfaced as the lever.
- **Binds:** `estimates[]` × the two costed quantities · `decision.crossover_qty`.

### 1.6 SHARE / HANDOFF — share the glass box, not the number (all roles)
`SharePanel` in `PartWorkspace.tsx` (elevated)

- Instant copy-summary (zero-friction) + **role-scoped handoff**: pick the recipient's lens, verb+noun actions ("Send to sourcing", "Forward to purchaser"), data-locality signal. The recipient opens the SAME provenance-tagged report in their own lens — "your numbers become yours" survives the handoff.

### 1.7 Build-proof showcase (pre-existing, kept)
`app/(app)/design-system/page.tsx` + `fixture.ts` — every glass-box component rendered against the engine's REAL captured output (object.stl · Midwest Precision CNC), light/dark, role-lens live. This is the canonical render of routing + confidence + the shop A/B Compare.

### 1.8 Shared derivations (new, pure)
`lib/cost-views.ts` — `pickEstimate`, `costedProcesses/Quantities`, `buildCompareRows`, `parseCalibration`, `blockersByProcess`. Every lens binds to the SAME real numbers; nothing invented between costed points.

---

## 2. Real engine output it's designed against (verified)

Captured live, not assumed:

- **CLI** `cd backend && .venv/bin/python -W ignore -m src.costing.cli ".venv/share/doc/gmsh/examples/api/object.stl" --qty 10,1000 --shop "Midwest Precision CNC"` → routing (`cnc_turning`, rotational, conf 0.80, reasoning paragraph), per-process should-cost with itemized drivers each tagged `MEASURED/SHOP/DEFAULT` + source, `confidence` bands ("assumption-based, not yet validated"), `Σ line items = unit cost`, decision (make `mjf`, crossover ≈ 1,962, tooling `injection_molding` conditional/`tooling_dfm_ready=false`).
- **Live API** `POST /api/v1/validate/cost/demo` → 200 with `estimates[].drivers` (MEASURED/DEFAULT), `line_items`, `decision`, `engine_feasibility`, `assumptions` (all DEFAULT — no shop applied).

The provenance tag is the atom; the confidence honesty rail renders the engine's `validated`/`label` **verbatim**; no surface prints a fabricated ±X% accuracy figure.

---

## 3. API / build gaps designed FOR (owned by the build harness)

The frontend handles each gap honestly — degrades gracefully and labels the gap on-screen, and lights up automatically when the API serves the field:

1. **`routing` + per-estimate `confidence` not yet on the live API.** The current engine *source* emits both (`report.py` `report_to_dict` line 25 + estimate `confidence`; verified via CLI), but the **running server is a stale process** that imported the engine before those fields existed — so the live `/validate/cost/demo` omits them today. Routing lens shows a build-gap note + still renders the DFM matrix; Decision/Glass Box render the answer + drivers and note the missing band. The instant the API serves them, the `RoutingCard`/`ConfidenceInterval` appear with no further frontend work.
2. **Per-shop calibration not surfaced through the API** (no `shop` param on `EstimateOptions`). Live reports are all `DEFAULT` → the `CalibrationBar` honestly reads "Not calibrated — generic defaults" (the gap is the CTA). Parsing already reads `assumptions` provenance + the engine's calibration `note`, so a SHOP-bound report lights the bar up.
3. **Multi-shop-in-one-call** (Midwest vs Shenzhen A/B). Compare uses the real volume-break board today and flags the shop A/B gap; the engine binds a shop per call, so a true A/B composes from two real reports.
4. **Server re-cost on shop-rate / driver overrides** and **persisted, versioned scenarios** — overrides re-tag `USER` locally and toast the gap; Save-as-scenario toasts the persistence gap.
5. **Role-scoped shareable analysis object** — the handoff designs the role-scoped link; the persisted object is the gap.

---

## 4. Thesis → structure (what's load-bearing, not a footnote)

- **Glass box is the hero:** a first-class tab *and* universal inline drill-down on every driver; the Σ=unit arithmetic always shown; DEFAULT rows flagged hollow (`◌`) so "where the model is guessing" is visible.
- **The decision, not the dollar:** Decision is the hero landing; cost is always banded; the crossover slider is the signature interaction; the "if redesigned" banner never asserts a process the part currently fails.
- **Role-aware:** one engine, five lenses set by the topbar Role Lens — opposing needs served without drowning anyone.
- **Your numbers become yours:** calibration is an always-on topbar fact; the not-calibrated gap is the call to action.
- **Validated on your parts (never fabricated):** confidence renders the engine's `validated`/`label` verbatim; today every band reads "assumption-based, not yet validated."

---

## 5. Build proof

- `npx tsc --noEmit` → **exit 0**.
- `npm run build` (Next.js 16 + Turbopack) → **exit 0**, "Compiled successfully", "Finished TypeScript". `/cost`, `/analyze`, `/design-system`, `/` prerendered (○ static).
- Live API verified: `POST http://localhost:8000/api/v1/validate/cost/demo` → 200 with real drivers/decision/feasibility.
- CLI verified: engine emits routing + confidence + crossover for object.stl.

(No interactive screenshots: this environment has no browser-driving/screenshot tool for the client-side upload flow. Per the honesty rule, none are fabricated — the green production build is the render proof; the `/design-system` route is the static render of every glass-box surface against real engine output.)

---

## 6. Acceptance self-audit

1. **Trustworthy decision fast + see/edit every assumption** ✓ — Decision hero (answer + banded cost + crossover slider) is the landing; "View glass box" drills any number to its provenance/source; Glass Box makes every assumption inline-editable (override → `USER`), Σ=unit always shown.
2. **Routing correctness + confidence legible** ✓ — Routing & DFM foregrounds the reasoning paragraph + measured deciding drivers + geometry-linked DFM matrix; confidence renders as a band with the verbatim honesty label wherever the API serves it (and a build-gap note where the stale API doesn't yet).
3. **Built on real engine outputs** ✓ — every lens binds to `report_to_dict` fields, verified by CLI + live API; the toy `cost_per_cm3` model is nowhere.
4. **Role-views present** ✓ — Design / Cost / Sourcing / Mfg / Buyer lenses, each a real landing set by the Role Lens, all cross-navigable.
5. **Builds green** ✓ — §5.

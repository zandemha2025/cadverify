# CadVerify — Information Architecture & Core Flows

**Role:** Design Strategist + IA Architect (the "audience-driven, not a reskin" layer).
**Goal:** Turn the research (`audience.md`, `design-landscape.md`) + the real Cost-Truth Engine outputs into the **information architecture**, the **role-aware views**, and the **core flows** — concrete enough that a designer can wireframe every core screen with **no further structural decisions**.
**Date:** 2026-06-29.
**Companion docs (do not duplicate):** `audience.md` (the 5 segments + opposing-needs matrix §3 — this doc *implements* that matrix), `design-landscape.md` (adopt/avoid pattern library), `design-direction.md` (locked visual language + north star), `design-system-spec.md` / `design-system-patterns.md` (tokens/components). This doc owns **structure + flows**, not pixels or tokens.

> **Acceptance bar this doc is written against (self-audited in §11):**
> 1. **Each of the 5 audience segments can reach its view from the IA** — a named landing, set by role, never drowned.
> 2. **The glass box and the decision are structurally central** — first-class destinations + universal drill-down, never a footnote.
> 3. **A designer could wireframe every core screen from this** — every surface has an engine-field binding + an ASCII wireframe + a disclosure rule.

---

## 0. The one structural idea everything hangs on

The hardest fact about this product (from `audience.md` §3): **one engine, five users who pull the interface in contradictory directions.** Averaging them produces aPriori's firehose (drowns the design engineer) *or* Xometry's funnel (starves the cost engineer). The resolution is **not** five apps and **not** one compromised middle. It is:

> **ROLE-GATED GLASS-BOX over ONE analysis object.**
> One report (`report_to_dict`). The glass box is *never hidden* — only **how much of it is open by default** is a per-role property. Every number, on every surface, is **drill-downable to its provenance-tagged, sourced, editable driver.** Role sets *defaults* (landing surface + density + disclosure state); nothing is walled off, because real users wear several hats in one sitting (the Zoox buyer is buyer + mfg engineer + cost engineer at the same table).

Three structural primitives carry this, and they are the whole IA:

| Primitive | What it is | Which tension it kills |
|---|---|---|
| **The Analysis Object** | One upload → one persistent `report_to_dict` that every surface is a *lens* onto (not five separate fetches). The part-as-object workspace already in the repo. | T2, T4 (one object, many zoom/compare lenses) |
| **The Role Lens** | A topbar selector (chosen or inferred) that sets the **landing tab + default density + default disclosure** per role. Sets defaults; walls nothing. | T1, T3, T8 (decide/deliberate, defaults/overrides, density) |
| **Universal drill-down** | *Every* figure anywhere expands **inline** (Vercel "inline before modal") to `{value, provenance, source, error_band}`. The glass box is reachable from any number, in any lens. | T5, T6 (the dollar→its drivers; speed *and* auditability) |

Everything below is these three primitives made concrete.

---

## 1. Product reality the IA is cut from (the real engine fields)

Designed against `report_to_dict` (verified by running the CLI + reading the JSON sidecar — **not** the toy `cost_per_cm3`). Every surface in this doc binds to these exact fields:

```
report_to_dict = {
  filename, status,                 # "OK" | "GEOMETRY_INVALID"
  reason,                           # repair reason when invalid
  geometry: {volume_cm3, bbox_mm[3], watertight, face_count, ...},   # MEASURED
  material_class,                   # "polymer" | "aluminum" | ...
  quantities: [q_lo, …, q_hi],
  estimates: [ {                    # one per (process, qty)
     process, material, quantity,
     unit_cost_usd, fixed_cost_usd, variable_cost_usd, est_error_band_pct,
     confidence: {low_usd, high_usd, point_usd, level, method,        # "measured-residual" | "assumption-band"
                  validated, n_samples, half_width_pct, basis, label},
     dfm_ready, dfm_verdict, dfm_score, dfm_blockers[],
     line_items: {amortized_fixed, material, machine, labor, …},      # Σ = unit_cost_usd
     drivers: [ {name, value, unit, provenance, source, error_band_pct} ],  # provenance ∈ MEASURED|USER|DEFAULT|SHOP
     lead_time: {low_days, high_days, components{…}, capacity{…}}
  } ],
  routing: {archetype, recommended_process, eval_family, material_hint,
            confidence, reasoning, alternatives[], drivers{…}},        # geometric routing + human reasoning
  engine_feasibility: [ {process, verdict, score, costed} ],          # DFM across ALL processes
  assumptions: [ {name, value, unit, provenance, source} ],           # every one editable
  decision: {make_now_process, make_now_material, tooling_process, tooling_dfm_ready,
             crossover_qty, recommendation{q→…}, if_redesigned{q→…}, note}
}
```

**The provenance tag is the atom of the whole product.** `MEASURED` (from geometry), `SHOP` (your calibrated rate), `USER` (you overrode it), `DEFAULT` (generic fallback = "we're guessing here"). It appears on every driver and every assumption, and it is what every surface renders, colors, and makes clickable.

**Per-shop calibration is real and load-bearing.** Same `object.stl`, swap the shop profile → different cost. The engine emits a calibration note: *"19 rate(s) bound to this shop's reality and tagged SHOP … Every other line stays a generic DEFAULT — the gaps are visible, not hidden."* Midwest Precision CNC (labor $52/hr, CNC-3axis $95/hr) vs Shenzhen ($14/hr, $45/hr) is the canonical A/B.

**The honesty rail (hard constraint).** `confidence.validated` is `false` for every part today (no ground truth yet); `label` reads **"assumption-based, not yet validated."** The UI renders that honesty verbatim. **No surface ever prints a fabricated ±X% accuracy number.** "Validated on your parts" is wired to `confidence.validated`/`n_samples`/`label` — it appears only when those flip on real residuals.

> **API/build gaps to design *for* (owned by build harness, flagged in §10):** `routing`, `confidence`, and per-shop calibration **live in the engine** (above) but are **not yet fully surfaced** through `/api/v1/validate/cost` → frontend. This doc designs as if they are available, because they will be.

---

## 2. The Information Architecture — three layers

The IA is **three nested zoom levels**, resolving T4 (part ↔ portfolio) as navigable structure rather than separate products:

```
L1  GLOBAL NAV ......... destinations + zoom (sidebar)
        │
L2  ANALYSIS OBJECT .... one part = one report, viewed through the Role Lens + tabs
        │
L3  UNIVERSAL DRILL-DOWN  every number → its provenance/source/driver, inline
```

### 2.1 — L1: Global navigation (evolve the existing sidebar, don't reinvent)

The repo already has `Sidebar` (groups: Analyze · Library · Develop) and `AppShell` (sidebar + topbar). Evolve it to a **zoom-aware** nav. Old → new mapping (so the build is an evolution):

| Existing nav | Becomes | Why |
|---|---|---|
| Analyze / Cost (two entries) | **New analysis** (one entry → the Part Workspace) | Part-as-object already merged the two; one front door, lens picks the landing |
| Batch | **Batch** (unchanged) | Bulk upload → portfolio feeder |
| — (new) | **Portfolio** | Buyer's program/portfolio roll-up (T4 top zoom) — the missing exec destination |
| History | **History / Scenarios** | Saved, named, versioned analyses (T7 persistence) |
| Label (Parts) | **Library / Parts** | unchanged role (corpus) |
| — (new) | **Shops** | Manage calibration profiles (`data/shop_profiles/`) — surfaces the per-shop pillar as a real destination |
| API keys / Docs | **Develop** (unchanged) | engine-as-MCP/API roadmap lives here |

Proposed sidebar:

```
WORKSPACE          LIBRARY              ENTERPRISE          DEVELOP
• New analysis     • History/Scenarios  • Portfolio         • API keys
• Batch            • Parts (Library)    • Shops (calib.)    • API docs
```

The **topbar** carries the *context* of the open object: part name · **Role Lens selector** · **Shop context** ("Calibrated to Midwest Precision CNC ▾") · primary actions (Save scenario · Share/Handoff). The Role Lens and Shop context living in the *topbar* (not buried in settings) is the structural assertion that **role-awareness and per-shop calibration are first-class, always-visible facts about the current view** — not preferences.

### 2.2 — L2: The Analysis Object (the Part Workspace) — anatomy

One upload runs the full report; the part stays in a **persistent 3D rail** (already built) while **tabs change the lens** and the **Role Lens sets which tab you land on**. Five tabs (the existing four — Analyze · Cost · Tolerances · Share — evolve; the glass box is *promoted out of a disclosure into a first-class tab*, and Compare is added):

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR:  bracket_v3.step    [Lens: Design ▾]   Calibrated to: Midwest CNC ▾   │
│                                              [Save scenario]  [Share / Handoff]│
├──────────────────────────────────────────────────────────────────────────────┤
│  ┌─ TABS ───────────────────────────────────────────────────────────────────┐ │
│  │  Decision* │ Glass Box │ Routing & DFM │ Compare │ Share                   │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────┐  ┌──────────────────────────────────────────────┐ │
│  │  PERSISTENT 3D RAIL     │  │  ACTIVE LENS CONTENT                          │ │
│  │  • part viewer          │  │  (Decision / Glass Box / Routing / Compare /  │ │
│  │  • DFM highlights ↔ issue│  │   Share — see §3)                            │ │
│  │  • MEASURED geom facts  │  │                                               │ │
│  │    (vol, bbox, faces,   │  │                                               │ │
│  │     watertight)         │  │                                               │ │
│  └────────────────────────┘  └──────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
   * = landing tab is set by the Role Lens (table in §2.4)
```

The 3D rail is **shared state** across tabs: click a DFM issue (Routing & DFM tab) → geometry highlights; click a face → jumps to its issue. This two-way link already exists (`onFaceClick` in `PartWorkspace`); it is table-stakes per `design-landscape.md` §1.2 and must hold across the new tabs.

### 2.3 — L3: Universal drill-down (the glass box, reachable from any number)

**Rule (binds every surface):** any rendered figure that comes from a `driver`, `assumption`, `line_item`, or `confidence` is a **drill-target**. Interacting with it expands **inline** (never a modal — `design-landscape.md` §3.4) to:

```
 $38.87  labor_cost                                    [SHOP ±20%]   ▸
 └─ expands inline ─────────────────────────────────────────────────────
    SHOP · post-process 0.5 hr × $52/hr × region-labor ×1
    source: Midwest Precision CNC — Shop accounting export 2026-Q2
    [ Override → ]   (re-tags USER, re-runs)
```

This is the **glass-box thesis as a UI primitive**: the provenance tag (`design-landscape.md` §4.2, "inline, passage-level, click-through citations") is rendered *on the number itself*. It exists in the answer-first Design lens too — just collapsed by default — so the glass box is never *behind a door*, only folded.

### 2.4 — The Role Lens: how each segment reaches its view (the core of "role-aware")

The Lens is one control (topbar) that sets **landing tab + default density + default disclosure**. It is the structural implementation of `audience.md` §3's opposing-needs matrix.

| Role (audience §2) | Verb | Lands on | Default density | Default disclosure | Reaches its view via |
|---|---|---|---|---|---|
| **Design / Mech Eng** (2.A) | **TWEAK** | **Decision** | airy | glass box *collapsed* | Lens=Design → Decision tab |
| **Cost / Value Eng** (2.B) | **OVERRIDE & AUDIT** | **Glass Box** | compact tables | glass box *open*, overrides first-class | Lens=Cost → Glass Box tab |
| **Sourcing / Procurement** (2.C) | **COMPARE & DECIDE** | **Compare** | medium, multi-column | crossover + shop A/B open | Lens=Sourcing → Compare tab |
| **Manufacturing / Process Eng** (2.D) | **VERIFY ROUTING** | **Routing & DFM** | medium | routing reasoning + DFM matrix open | Lens=Mfg → Routing & DFM tab |
| **Enterprise / Economic Buyer** (2.E) | **TRUST & APPROVE** | **Decision** + Trust panel | airy | decision + method/trust panel open; *clickable down* | Lens=Buyer → Decision tab (trust panel) → drill or → Portfolio (L1) |

**Every cell is a real landing.** No segment is averaged away; no segment is drowned. The lens sets the *door you walk in*, but all five tabs + the portfolio zoom remain one click away for everyone (the multi-hat reality). Per `audience.md` §4, **Buyer + Sourcing are the front-door beachhead**, Design is the everyday workspace, Cost + Mfg are the depth that makes the others trustable — which is exactly why their lenses land on the *deep* tabs (Glass Box / Routing) that the front-door roles drill *into*.

> **Build note (gap):** start with an **explicit** lens switcher (cheap, honest); *infer* the lens later (e.g., from which tab a user repeatedly opens, or from SSO role). The lens is a client-side default-setter over one report — no engine change. Role-*scoped shared* views (handoff, §6.5) are the only part needing API work.

---

## 3. The surfaces (each tab = a lens), with field bindings + wireframes

Every surface below states: **purpose · primary role · engine fields it binds · ASCII wireframe · disclosure rule.** A designer wireframes directly from these.

### 3.1 — DECISION (the hero answer) — *Design + Buyer land here*

**Purpose.** The thesis output: **the decision, not the dollar.** Make-vs-buy + the quantity crossover + a confidence-*banded* cost + lead time. The signature interaction (`design-direction.md`): a **quantity slider that live-flips the recommended process at the crossover.** This surface already exists (`CostDecisionView.tsx`) and is at the bar — elevate, don't rebuild.

**Binds:** `decision.{make_now_process, crossover_qty, recommendation{q}, if_redesigned{q}, note}` · `routing.recommended_process` (the geometry pick, shown alongside the cost pick) · `estimates[].confidence` (the band) · `estimates[].lead_time`.

```
┌─ DECISION ─────────────────────────────────────────────────────────────────┐
│  RECOMMENDED DECISION · make-vs-buy                                          │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Make by MJF (PP)              ● DFM-ready                              │  │
│  │  MJF wins below ~1,962 units; tool up with injection molding above it. │  │
│  │  ┌──────────────┬──────────────┬──────────────────────────────────┐    │  │
│  │  │ COST / UNIT  │ LEAD TIME    │ AT QUANTITY                       │    │  │
│  │  │ $14.14       │ 5.6–10.4 d   │ [====slider 10 ◀───●──▶ 1000===]  │    │  │
│  │  │ ± band ▸     │              │  crossover ≈ 1,962               │    │  │
│  │  └──────────────┴──────────────┴──────────────────────────────────┘    │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│  ┌─ MAKE-VS-BUY BREAKEVEN  ($/unit vs qty) ──────────────────────────────┐  │
│  │   $/u                       MJF ───────╲                               │  │
│  │       │  inj.molding ╲__________________╳____  ← crossover q*=1,962    │  │
│  │       └──────────────────────────────────────── qty →                 │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│  ⚠ injection molding requires design-for-molding (FAILS draft DFM now) —     │
│     cost shown is "if redesigned", not a current quote.   [see Routing ▸]    │
│                                                                              │
│  ▸ Adjust inputs & re-cost   (material · region · qty · cavities)            │
│  ▸ View glass box            (drivers · provenance · Σ=unit · confidence)    │
│  ┌─ [Buyer lens only] WHY TRUST THIS ───────────────────────────────────┐   │
│  │ Method: glass-box drivers · per-shop calibration · held-out error     │   │
│  │ Confidence: ±40% — assumption-based, NOT yet validated (no ground     │   │
│  │   truth yet). Validates on YOUR parts as residuals accrue.            │   │
│  │ Data locality: ● IP-local, zero network egress (CAD-as-IP)           │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Disclosure rule.** *Design lens:* the two `▸` rows (inputs, glass box) collapsed; Why-Trust hidden. *Buyer lens:* Why-Trust panel **open** (it is the trust artifact), glass box collapsed-but-prominent (the buyer is technical and *will* drill — `audience.md` §2.E nuance). The qty slider defaults its handle to `crossover_qty` (the decision boundary) — already the behavior in `CostDecisionView`.

**The "if redesigned for molding" banner is non-negotiable honesty:** when `decision.tooling_dfm_ready == false`, the crossover is real but the tooling route is *conditional* — say so, link to Routing & DFM. Never assert a process the part currently fails (`decision.py` guarantees the headline make is DFM-ready; the UI must preserve that distinction).

### 3.2 — GLASS BOX (driver-level, the open model) — *Cost Eng lands here*

**Purpose.** `audience.md` §2.B: *the glass box, fully open.* Every line item, **provenance-tagged + sourced**, **summing visibly to the unit cost**, **every assumption inline-editable** (override → re-tag `USER` → re-run), confidence with its **basis** spelled out. This is the inverse of the Decision lens: depth is the *default*. Promoted from the existing progressive-disclosure card into a first-class tab.

**Binds:** `estimates[].drivers[] {name,value,unit,provenance,source,error_band_pct}` · `estimates[].line_items` (Σ check) · `assumptions[]` · `estimates[].confidence.{basis,label,validated,method,half_width_pct}`.

```
┌─ GLASS BOX ──────────────────────── process: [MJF ▾]  qty: [10 ▾]  [▣ compact]┐
│  DRIVER                  VALUE      PROVENANCE   SOURCE (click → full)          │
│  ───────────────────────────────────────────────────────────────────────────  │
│  material_cost          $0.04      ● SHOP       CAD vol 4.63cm³ × PP … ±5%  ▸   │
│  parts_per_build        223        ◌ DEFAULT    nesting packing 0.1 …      ▸   │
│  machine_cost           $3.82      ● SHOP       0.068hr × $30/hr ÷0.8 …  ±40% ▸ │
│  labor_cost             $6.39      ● SHOP       finish 0.08hr + bulk … ±20%  ▸  │
│  amortized_fixed        $3.89      ● SHOP       setup 0.5hr × $52/hr …     ▸    │
│  ───────────────────────────────────────────────────────────────────────────  │
│  Σ LINE ITEMS = $14.14 / unit   (material 0.04 + machine 3.82 + labor 6.39 +   │
│                                   fixed 3.89)   ✓ sums to unit cost            │
│  ┌─ CONFIDENCE ─────────────────────────────────────────────────────────────┐ │
│  │  80%: $8.49 – $19.80 / unit  (±40%)                                        │ │
│  │  ◷ assumption-based, NOT yet validated — ±40% stated band (cycle-time/     │ │
│  │    tooling defaults), no ground truth yet.   method: assumption-band      │ │
│  └───────────────────────────────────────────────────────────────────────────┘ │
│  ┌─ ASSUMPTIONS (every one editable) ───────────────────────────────────────┐  │
│  │  labor_rate  $52/hr  ●SHOP  [override]    margin 0.3 ●SHOP  [override]    │  │
│  │  utilization 0.8 ●SHOP       stock_allow 1.1× ◌DEFAULT [override]         │  │
│  │  n_cavities 1 ◌DEFAULT [override]   complexity moderate ◌DEFAULT          │  │
│  └───────────────────────────────────────────────────────────────────────────┘ │
│  [+ Save as scenario]   (promotes this override-set into History/versioned)    │
└────────────────────────────────────────────────────────────────────────────────┘
   ● = SHOP/MEASURED (calibrated/measured)   ◌ = DEFAULT (generic — "guessing here")
```

**Disclosure rule.** Cost lens: everything open, `[▣ compact]` density toggle on (`design-landscape.md` §3.1, right-aligned tabular numerics, frozen first column). Override is **inline** (edit the cell → re-tags `USER` → re-runs the report) — Vercel "inline before modal." The `Σ = unit cost` row is **always visible** (no naked numbers — the report already enforces it; the UI must *show the arithmetic*). The DEFAULT rows are visually quieter-but-flagged (`◌`) so the cost engineer instantly sees *where the model is guessing* — that's the honesty the persona trusts more, not less.

### 3.3 — ROUTING & DFM (is it made the right way) — *Mfg Eng lands here*

**Purpose.** `audience.md` §2.D: routing-correctness + DFM audit. The **routing card** (archetype, recommended process, confidence, **the reasoning paragraph** — the trust object for this persona) over the **measured drivers that decided it**, plus a **per-process DFM matrix** (verdict + blockers, geometry-linked). Merges the existing Analyze dashboard with the engine's `routing`.

**Binds:** `routing.{archetype, recommended_process, confidence, reasoning, alternatives[], drivers{}}` · `engine_feasibility[] {process,verdict,score,costed}` · `estimates[].{dfm_ready,dfm_verdict,dfm_blockers}` · the 3D rail (face↔issue link).

```
┌─ ROUTING & DFM ───────────────────────────────────────────────────────────────┐
│  GEOMETRIC ROUTING                                                              │
│  ┌───────────────────────────────────────────────────────────────────────────┐ │
│  │ → CNC TURNING       archetype: rotational      confidence 0.80             │ │
│  │ "Axisymmetric cross-section (round, turnable): axis 21mm × Ø21mm → CNC     │ │
│  │  turning / mill-turn. A round metal part is rarely powder-bed printed at   │ │
│  │  production volume."                                                       │ │
│  │ alternatives: cnc_5axis · mjf                                              │ │
│  │ decided by [MEASURED]:  rotational ✓ · planar_aspect 1.01 · wall 6.17mm    │ │
│  └───────────────────────────────────────────────────────────────────────────┘ │
│  ⓘ Note: cost-cheapest make is MJF; geometry-recommended is CNC turning — pick  │
│     on intent, not the marginal $.  (both are costed → Compare ▸)               │
│  ┌─ DFM MATRIX (all processes) ─────────────────────────────────────────────┐  │
│  │ PROCESS         VERDICT    SCORE   COSTED   BLOCKER (geometry-linked)      │  │
│  │ mjf             ● issues    0.9     yes      —                             │  │
│  │ cnc_turning     ● issues    0.9     yes      —                             │  │
│  │ cnc_3axis       ✕ fail      0.0     yes      423 faces (59.6%) undercut →  │  │
│  │                                              [highlight on part]           │  │
│  │ injection_mold  ✕ fail      0.0     yes      1 sidewall <1.0° draft →[show]│  │
│  │ sheet_metal     ● issues    0.8     no       —                            │  │
│  └───────────────────────────────────────────────────────────────────────────┘ │
│  Click a blocker → the offending faces light up in the 3D rail (two-way).       │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Disclosure rule.** Mfg lens lands here with reasoning + matrix open. The DFM rows are **actionable, not red flags** (`design-landscape.md` §4.1): each blocker states the measured value vs the threshold and links to geometry. `costed=no` rows are feasibility-only (engine ran DFM but didn't cost) — visually de-weighted, honestly labeled.

### 3.4 — COMPARE (the decision board) — *Sourcing lands here*

**Purpose.** `audience.md` §2.C: the only surface where **multiple answers coexist on equal footing.** Columns of **process × shop × quantity**, each cell a **banded** cost with expandable drivers; the **crossover chart** as centerpiece; export to a negotiation-ready breakdown. This is the make-vs-buy / shop-A-vs-shop-B / region surface.

**Binds:** the full `estimates[]` set × a *second* report from another shop profile (`data/shop_profiles/*`) · `decision.crossover_qty` · `confidence` per cell · drivers per cell (drill-down).

```
┌─ COMPARE ──────────────────  shops: [Midwest CNC] vs [Shenzhen ▾]  qty: [1000]─┐
│                    │ MIDWEST PRECISION CNC │ SHENZHEN CONTRACT MFG │ Δ          │
│  ──────────────────┼───────────────────────┼───────────────────────┼────────── │
│  MJF (PP)          │ $10.45  ±40%  ▸drivers │ $6.80   ±40% ▸drivers │ −35%      │
│  CNC turning       │ $26.92  ±50%  ▸        │ $15.10  ±50% ▸        │ −44%      │
│  Injection molding │ $14.25  ±60% ⚠redesign │ $9.90   ±60% ⚠        │ −30%      │
│  ──────────────────┴───────────────────────┴───────────────────────┴────────── │
│  rate that diverges most:  labor_rate  $52/hr ●SHOP  vs  $14/hr ●SHOP           │
│      → negotiation lever: "your setup implies ½ our expected rate for this      │
│         machine class"  (driver-level, not a total)                            │
│  ┌─ MAKE-VS-BUY CROSSOVER (overlaid both shops) ───────────────────────────┐   │
│  │  curves cross at q* per shop → where the make/buy flips for each         │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│  [Export negotiation breakdown ▾]  (driver structure, not your target total)    │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Disclosure rule.** Sourcing lens lands here, two shops side by side, crossover open. Every cell is **banded** (T5: a number *with its bounds and drivers* is more wieldable in a negotiation than a fake-exact point). Each cell drills to its glass box (universal drill-down). **Confidence is leverage, not false precision** — and still never a fabricated validated figure.

### 3.5 — CALIBRATION (the per-shop pillar) — *topbar context + panel, woven through Glass Box & Compare*

**Purpose.** Make per-shop calibration a *visible, always-on fact about the current view*, not a hidden config (`design-landscape.md` §2.4: "calibrated to <shop>, here's each rate's source"). It is **not a 6th tab** — it's the **topbar "Calibrated to <shop> ▾"** control (swap shop → whole report re-costs) plus a **panel** that expands to show which rates are `SHOP` vs `DEFAULT` and their sources.

**Binds:** `assumptions[]` provenance split · the calibration `note` ("19 rates bound … gaps visible, not hidden") · `data/shop_profiles/<shop>.json` (rates + `source` string).

```
┌─ Calibrated to: Midwest Precision CNC ▾ ──────────────────────────────────────┐
│  Source: Shop accounting export 2026-Q2 (loaded rates + negotiated resin lots)│
│  19 rates bound to THIS shop, tagged ●SHOP. Everything else stays ◌DEFAULT —   │
│  the gaps are visible, not hidden.                                            │
│  ●SHOP   labor $52/hr · CNC-3ax $95/hr · MJF $30/hr · margin 0.3 · util 0.8   │
│  ◌DEFAULT stock_allowance 1.1× · daily_machine_hours 8 · n_cavities 1         │
│  [Swap shop → re-cost]      [Open shop profile]      [+ New calibration]       │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Disclosure rule.** Collapsed to the topbar pill by default; expands on click in any lens. This is the structural home of *"your numbers become yours"* — and the A/B (Midwest vs Shenzhen) *is* the Compare surface (§3.4).

### 3.6 — SHARE / HANDOFF (designer → purchaser, role-aware made literal) — *all roles*

**Purpose.** `design-landscape.md` §1.4 upgraded: **share the glass box, not the number.** The recipient lands on the same provenance-tagged, editable report *in their own lens* — "your numbers become yours" survives the handoff. The existing Share tab does an instant copy-summary (keep as the zero-friction path) + adds the role-scoped shared object.

**Binds:** the whole `report_to_dict` as a shareable object · recipient's Role Lens.

```
┌─ SHARE / HANDOFF ─────────────────────────────────────────────────────────────┐
│  ○ Copy decision summary        (instant, no account — the text answer)         │
│  ○ Share glass box →                                                            │
│      recipient opens as:  ( ) Design  ( ) Cost  (•) Sourcing  ( ) Buyer         │
│      ☑ include overrides & scenario   ☑ include calibration (shop rates+source) │
│      → "Forward to purchaser"  /  "Send to sourcing"                             │
│  ○ Export PDF / deck            (take-it-to-a-meeting — Buyer)                   │
│  Link is role-scoped + audit-logged.  ● IP-local: geometry not egressed.        │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Disclosure rule.** Verb+Noun actions (`design-landscape.md` §3.4): "Forward to purchaser", "Send to sourcing", "Share glass box with cost engineer" — never "Confirm/OK". The recipient's lens defaults to the *handoff target's* role (a designer sending to a purchaser → recipient lands in **Sourcing** lens on **Compare**).

### 3.7 — PORTFOLIO (the buyer's roll-up zoom) — *Buyer; global nav L1*

**Purpose.** `audience.md` §2.E + T4: savings + de-risked decisions rolled up across parts/program, exportable to a deck — **but every headline number stays clickable down into the glass box** (the buyer is technical and drills). Lives in **global nav** (it's a zoom *above* the part), not a part tab.

**Binds:** aggregate over many saved `report_to_dict` objects (History/Scenarios) · `decision` per part · `confidence` per part.

```
┌─ PORTFOLIO ─ program: [EV powertrain NPI ▾] ──────────────────────────────────┐
│  PARTS 42 · costed 42 · make 31 · tool-up candidates 11 · ◌DEFAULT-heavy 6 ⚠   │
│  ┌─ ROLL-UP ──────────────────────────────────────────────────────────────┐   │
│  │ Modeled spend @ plan volume   $1.42M   (banded — see method)           │   │
│  │ Make-vs-buy decisions de-risked   31 / 42                              │   │
│  │ Confidence posture: 36 assumption-based, 6 calibrated, 0 validated*    │   │
│  │   *no ground truth yet — validates on your parts (Zoox session)        │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│  PART          DECISION              UNIT@vol   CONFIDENCE     →                │
│  bracket_v3    Make · MJF            $10.45     ◷ assumption   [open glass box] │
│  housing_A     Tool-up >1,962        $14.25     ◷ assumption   [open]          │
│  …             …                     …          …                              │
│  [Export program deck ▾]   ● zero network egress · audit trail on              │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Disclosure rule.** Airy roll-up tiles; every row drills into that part's Workspace (Buyer lens). The "confidence posture" line is the **honesty rail at portfolio scale** — it counts how many parts are assumption-based vs validated and **never** rolls up to a fabricated accuracy figure.

---

## 4. FLOW MAP — the core flows

### F0 — MASTER FLOW (the thesis spine: upload → routing → glass-box cost → calibrate → decision)

This is the one flow the whole product is. It is **answer-first with the glass box folded outward on demand**, and it threads all five engine outputs in the order a user actually consumes them.

```
                              ┌───────────────────────────────────────────────┐
   ┌──────────┐               │                ANALYSIS OBJECT                 │
   │  UPLOAD   │   one drop    │  (one report_to_dict, viewed via Role Lens)   │
   │ STL/STEP  │ ───────────▶  │                                               │
   └──────────┘   runs cost    │   ┌─ (1) MEASURED GEOMETRY ─────────────┐     │
        │         + DFM        │   │ vol·bbox·faces·watertight  [3D rail] │     │
        │         in-process   │   └─────────────────┬────────────────────┘     │
        │  (CAD parsed &       │                     ▼                          │
        │   discarded;         │   ┌─ (2) GEOMETRIC ROUTING ─────────────┐     │
        │   zero egress)       │   │ archetype → recommended process +    │     │
        ▼                      │   │ REASONING paragraph + alternatives   │ ◀── Mfg lens lands
   ┌──────────────┐           │   └─────────────────┬────────────────────┘     │
   │ GEOMETRY     │  invalid  │                     ▼                          │
   │ valid?       │ ────────▶ │   ┌─ (3) GLASS-BOX COST per process ────┐     │
   └──────┬───────┘  REPAIR   │   │ drivers (MEASURED/SHOP/USER/DEFAULT) │ ◀── Cost lens lands
          │ ok       state    │   │ Σ line items = unit cost            │     │
          │                   │   │ + CONFIDENCE band (validated? basis) │     │
          │                   │   └─────────────────┬────────────────────┘     │
          │                   │                     ▼                          │
          │                   │   ┌─ (4) CALIBRATE (shop's real #s) ────┐     │
          │                   │   │ "Calibrated to <shop>" — SHOP vs    │ ◀── topbar context,
          │                   │   │ DEFAULT rates + sources; swap shop  │     always visible
          │                   │   └─────────────────┬────────────────────┘     │
          │                   │                     ▼                          │
          │                   │   ┌─ (5) THE DECISION ──────────────────┐     │
          │                   │   │ make-vs-buy + crossover q*           │ ◀── Design + Buyer land
          │                   │   │ qty slider live-flips process       │     │
          │                   │   │ banded cost · lead time             │     │
          │                   │   └─────────────────┬────────────────────┘     │
          │                   └─────────────────────┼──────────────────────────┘
          ▼                                         ▼
   ┌─────────────┐                   ┌──────────────────────────┐
   │ Repair /    │                   │  TWEAK-RERUN (F1)  ──────────┐ live loop
   │ re-upload   │                   │  COMPARE (F3) · HANDOFF (F5)  │
   └─────────────┘                   └──────────────────────────────┘
```

The lens just changes **where you enter** this loop (which numbered stage is your landing). Every stage is reachable from every lens via tabs + drill-down. **This is the positioning made structural:** the glass box (stage 3) and the decision (stage 5) are the two load-bearing stages, and stage 3 is reachable from *every* number in stage 5.

### F1 — Tweak-rerun loop (Design eng — the habit driver)

```
   adjust input (material / region / qty / cavities)  ──┐
        ▲                                               │  re-cost
        │                                               ▼
   read NEW decision  ◀── banded cost + crossover ◀── report re-runs (skeleton, optimistic)
        │
        └─ qty slider: NO server round-trip — live-flips process from the report's
           own fitted curves (already in CostDecisionView). Instant = "it knows."
```
**Loop integrity:** the slider (client-side, instant) vs the input-change re-cost (server, skeleton+optimistic, `design-landscape.md` §3.2). Ephemeral by default; **"Save as scenario"** promotes it to persisted/versioned (T7).

### F2 — Override & audit (Cost eng)

```
Glass Box → click a DEFAULT/SHOP driver → inline expand (value·source·band)
   → [Override] → edit cell → re-tags USER → re-run → Σ updates, band updates
   → [+ Save as scenario]  (named, versioned; audit trail of what changed & why)
   → Compare two scenarios side by side (T7 persistence)
```

### F3 — Compare & make-vs-buy (Sourcing)

```
Compare tab → pick shop A vs shop B (and/or process A vs B) at qty
   → banded cells + Δ% + most-divergent driver (the negotiation lever)
   → crossover chart (per shop) → where make/buy flips
   → [Export negotiation breakdown]  (driver STRUCTURE, not your target total)
```

### F4 — Verify routing (Mfg eng)

```
Routing & DFM → read archetype + REASONING paragraph (the trust object)
   → check measured drivers that decided it (rotational? wall? aspect?)
   → DFM matrix: per-process verdict + blocker → click blocker → faces light in 3D
   → confirm "recommended process is right for THIS geometry" or flag it
```

### F5 — Designer → purchaser HANDOFF (role-aware, the literal thesis)

```
DESIGNER (Design lens, Decision tab)                 PURCHASER (Sourcing lens)
   reads answer, tweaks ───────────┐
   [Share glass box →]             │  role-scoped link
   recipient lens = Sourcing       │  (audit-logged, zero CAD egress)
   ☑ overrides ☑ calibration ──────┴──────────────▶  opens SAME report, in
                                                      COMPARE lens — provenance,
                                                      bands, shop rates intact.
                                                      "your numbers became yours."
                                                      → negotiates from driver-level
                                                        should-cost, not a total
```
The handoff carries the **model**, not a flattened number — this is `audience.md`'s role-aware pillar made into a single button. (Build gap: role-scoped shared analysis object — §10.)

### F6 — Buyer trust & roll-up

```
Buyer lens → Decision tab + WHY-TRUST panel (method · confidence honesty ·
   data-locality badge) → drills any number into glass box (technical buyer)
   → Portfolio (L1 zoom): savings + decisions de-risked + CONFIDENCE POSTURE
     (assumption vs calibrated vs validated — never a fabricated %)
   → [Export program deck]  → approve / fund
```

---

## 5. Reachable states (design every reachable state — not just the happy path)

Per `design-landscape.md` §3.4: *a confident wrong answer is the trust-killer for this buyer.* Every surface designs these:

| State | Trigger (engine) | What the UI does |
|---|---|---|
| **GEOMETRY_INVALID** | `status=="GEOMETRY_INVALID"` (vol ≤ 0 / non-watertight) | No cost produced. Show the repair reason + the MEASURED geometry that failed; route to repair/re-upload. (Already handled — `CostGeometryInvalidCard`.) |
| **DEFAULT-heavy / low-confidence** | many `DEFAULT` drivers; `confidence.validated==false`, wide `half_width_pct` | Band reads **"assumption-based, not yet validated"**; DEFAULT rows flagged `◌`; Buyer/Portfolio count it in "confidence posture." Honest, not hidden. |
| **DFM-fail but costed** | `dfm_ready==false` with a cost (the molding route) | Decision shows the crossover but banners **"if redesigned — currently FAILS draft DFM"**; never asserts it as a current quote. Links to Routing & DFM blocker. |
| **No crossover** | `decision.crossover_qty==null` | "Make process X is cheapest at every quantity tested — no tooling crossover." Slider still works; no false q*. |
| **No shop selected (generic)** | all rates `DEFAULT` | Topbar reads "Not calibrated — generic defaults"; prompts "Calibrate to a shop to make these numbers yours." The gap is the call-to-action. |
| **Demo vs authed** | no API key → demo routes | Banner: local demo, CAD parsed & discarded in-process; STL triangle cap messaging (already built). Save/Share/Portfolio prompt for a key. |
| **Re-costing** | server round-trip in flight | Optimistic UI + skeletons (slow reads as "guessing"; instant reads as "it knows"). |

---

## 6. Opposing-needs matrix → structural resolution (implements `audience.md` §3)

| # | Tension | Structural resolution in THIS IA |
|---|---|---|
| **T1** Decide vs Deliberate | **Role Lens** sets disclosure: Design lands Decision (glass box collapsed); Cost lands Glass Box (open). Same object. |
| **T2** Commit vs Compare | Two surfaces off one report: **Decision** tab (committed answer) vs **Compare** tab (board). Not a compromised middle. |
| **T3** Locked defaults vs Open overrides | **Universal drill-down + inline override**: invisible to Design, first-class in Glass Box. Shared mechanism = the provenance tag (`DEFAULT→USER`), dialed by lens. |
| **T4** Part vs Portfolio | **Zoom levels in L1/L2**: Workspace (part) ↔ Portfolio (program), drill-down both ways. |
| **T5** Dollar vs Decision | **Banded driver breakdown everywhere**: every cost carries its `confidence` band + drills to drivers. Sourcing gets a wieldable number-with-bounds; thesis keeps the decision as hero. |
| **T6** Speed vs Auditability | **AI-native *and* traceable**: instant slider/optimistic re-cost (speed) over a glass-box substrate (audit). Never speed *instead of* traceability. |
| **T7** Ephemeral vs Persisted | **"Save as scenario"** promotes the live tweak loop into named/versioned History (audit trail). |
| **T8** Glanceable vs Dense | **Density is a Lens property**: airy Decision (Design) vs compact `[▣]` driver tables (Cost), both executed well (Linear's "every element earns its place"). |

---

## 7. Positioning ↔ Design bridge (the glass-box thesis, shown structurally)

The marketing thesis (*incumbents are opaque black boxes; transparency is the wedge*) is not a footnote in this IA — it is **load-bearing structure**. Each claim maps to a structural element a designer must build:

| Marketing claim (must match platform reality) | Where it shows up STRUCTURALLY |
|---|---|
| "Glass box, not a black box" | **Glass Box is a first-class tab** (not a disclosure) + **every number drills to its provenance** (universal drill-down, L3). The model is the UI. |
| "Every cost driver visible, cited, editable" | Driver table with **provenance tag + source string + inline override** on every line; **Σ = unit cost** always shown. |
| "Your numbers become yours" (per-shop calibration) | **Topbar "Calibrated to <shop>"** always visible + Calibration panel (SHOP vs DEFAULT + sources) + **Compare** A/B (Midwest vs Shenzhen). |
| "The decision, not the dollar" | **Decision tab is the hero landing**; cost is always **banded**, never fake-exact; **crossover slider** is the signature interaction. |
| "Validated on your parts" (NEVER a fabricated ±X%) | Confidence UI renders `validated`/`label` verbatim: **"assumption-based, not yet validated"** today; "validated on N of your parts" only when `validated==true`. Portfolio "confidence posture" counts it honestly. |
| "Shows its work / honest about guessing" | **DEFAULT rows flagged `◌`**; **DFM-fail-but-costed** banner; **low-confidence state** designed, not hidden. The gaps are the call-to-action. |
| "Runs locally, CAD-as-IP, zero egress" (ITAR/AS9100 adjacent) | **Data-locality badge** in Why-Trust panel + Share + Portfolio; demo path parses & discards in-process. A visible trust signal, not a buried PDF. |
| "AI-native, but auditable" | AI assistant (roadmap) **points at on-screen drivers** ("why $14.14? → these line items") and acts via the same overrides — explains a model you can already see, vs aPriori's chatbot-over-a-black-box. |

---

## 8. What to KEEP vs ELEVATE (so this is an evolution, not a reinvention)

**Keep (already at the bar):** `AppShell` (sidebar+topbar), the **part-as-object workspace** + persistent 3D rail (`PartWorkspace`), the **answer-first `CostDecisionView`** (hero + qty slider + breakeven + progressive disclosure), the face↔issue two-way DFM link (`onFaceClick`), `lib/status.ts` single status map, the `lib/api*` data layer, the demo/authed switch.

**Elevate (this doc's structural deltas):**
1. **Add the Role Lens** to the topbar (sets landing tab + density + disclosure). *New, but client-side over one report.*
2. **Promote the glass box** from a `▸ disclosure` inside Decision to a **first-class Glass Box tab** (Cost lens lands there). Keep the disclosure version inside Decision for the Design lens.
3. **Add a Compare tab** (process × shop × qty board + crossover). *New surface; needs multi-shop report — build gap.*
4. **Merge Analyze → Routing & DFM**, foregrounding `routing.reasoning` + the DFM matrix (Mfg lens).
5. **Surface calibration** as a topbar "Calibrated to <shop>" context + panel (Shops becomes an L1 destination).
6. **Add Portfolio** (L1) for the buyer roll-up; **History → History/Scenarios** (T7 persistence).
7. **Upgrade Share → Handoff** (role-scoped shared *glass box*, not a number).

---

## 9. Tab ↔ Role ↔ Engine-field cross-check (the wiring table)

| Tab (surface) | Lands for | Hero engine field | Drill-down field | Reachable state owned |
|---|---|---|---|---|
| **Decision** | Design, Buyer | `decision` + `confidence` | `estimates[].drivers` (inline) | no-crossover; DFM-fail-costed |
| **Glass Box** | Cost | `estimates[].drivers` + `line_items` | `assumptions` (override) | DEFAULT-heavy / low-confidence |
| **Routing & DFM** | Mfg | `routing.reasoning` | `engine_feasibility` + `dfm_blockers` | feasibility-only (uncosted) |
| **Compare** | Sourcing | multi-shop `estimates` + `crossover_qty` | per-cell `drivers` | one-shop / not-calibrated |
| **Share / Handoff** | all | whole `report_to_dict` | recipient lens | demo (no key) |
| **Calibration** (topbar+panel) | all (Cost/Sourcing) | `assumptions` provenance + shop `source` | shop profile JSON | not-calibrated |
| **Portfolio** (L1) | Buyer | aggregate `decision` + `confidence` | per-part report | DEFAULT-heavy program |

---

## 10. API / build gaps flagged (owned by build harness, not design)

Design assumes these; build must deliver them (consistent with `design-landscape.md` §6):
1. **Surface `routing`, `confidence`, per-shop calibration through `/api/v1/validate/cost`** — they live in `report_to_dict` (verified) but aren't fully exposed to the frontend yet. Decision/Glass Box/Routing/Compare all need them.
2. **Multi-shop cost in one call** (for Compare §3.4 and the Midwest-vs-Shenzhen A/B) — currently one shop per call.
3. **Role-scoped shareable analysis object** (Handoff F5, Share §3.6) — currently a single interactive page, not a persisted/shareable/role-scoped object.
4. **Persisted, versioned scenarios** (T7, "Save as scenario") — needed for Glass Box overrides + Compare + History/Scenarios.
5. **Portfolio aggregation** over saved reports (L1 §3.7) — new read surface.
6. **Engine-as-MCP-server / headless trigger** (`report_to_dict` is the natural payload) — for AI-native + CAD/PLM/forward-RFQ ingestion (roadmap, `design-landscape.md` §4.3–4.4).

The **Role Lens itself needs no engine change** (client-side default-setter over one report) — ship it first; it's the cheapest, highest-leverage structural move.

---

## 11. Acceptance self-audit

**(1) Each audience segment reaches its view from the IA.** ✓ — Role Lens routing table (§2.4): Design→Decision, Cost→Glass Box, Sourcing→Compare, Mfg→Routing & DFM, Buyer→Decision+Trust→Portfolio. Each is a named landing, set by role, none averaged away, all cross-navigable (multi-hat).

**(2) Glass box + decision are structurally central, not buried.** ✓ — Glass Box is a first-class tab *and* the universal drill-down on every number (L3) *and* the topbar calibration context. The Decision is the hero landing for the two front-door roles + the qty-slider signature interaction. The master flow (F0) makes stages 3 (glass-box cost) and 5 (decision) the two load-bearing stages, with 3 reachable from every number in 5. §7 maps every marketing claim to a structural element.

**(3) A designer can wireframe every core screen with no further structural decisions.** ✓ — §3 gives every surface a purpose + role + exact engine-field binding + ASCII wireframe + disclosure rule; §5 designs every reachable state; §9 is the wiring table; §4 is the flow map. The visual language (color/type/density/components) is owned by `design-direction.md` + `design-system-spec.md` and intentionally not re-decided here.

**Open dependencies for the build:** §10 gaps. None block the *structure* — they are exposure/persistence work over an engine that already emits everything the IA needs.
</content>
</invoke>

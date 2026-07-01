# CadVerify Self-Audit — what it actually is when you run it

Date: 2026-06-29. Method: logged into the live app (frontend :3000 / backend :8000, all
authed pages return 200), ran the CLI engine on ~8 real parts from the corpus, hit the live
`/validate/cost/demo` API, and read the rendered React + the engine source. Every point below
cites the exact screen or file. No flattery, no nitpicking-for-its-own-sake — material to a buy
or to "looks like real software" only. Most embarrassing first.

The one-line read: **the engine is real and genuinely glass-box; the live *product* is a thin,
partly-cosmetic shell over it that cannot yet do the two things the marketing site leads with
(per-shop calibration, edit-and-re-run), and its routing layer headlines a process its own DFM
check hard-fails.**

---

## AXIS 1 — CORRECTNESS / TRUST (the most damaging gaps)

### 1.1 The headline wedge — per-shop calibration — does not exist in the live product. [most embarrassing]
The homepage leads with it ("Per-shop calibration → Your numbers become yours", `frontend/src/app/page.tsx:139-172`)
and the hero shows `$14.14`/unit "Calibrated to Midwest Precision CNC". The live product cannot produce that number:

- The cost API takes `qty, region, cavities, complexity, material_class` and **no `shop` param**
  (`backend/src/api/routes.py:585-615`); `EstimateOptions` is built with no shop profile (`routes.py:508-517`).
- I hit the live endpoint with a real part: the response has **zero shop keys**
  (`curl …/validate/cost/demo` → `shop-related keys: []`), every assumption tagged `DEFAULT`
  (`labor_rate $35/hr [DEFAULT]`), returns the generic `$64.63/unit` for MJF.
- So `parseCalibration` returns `shopName: null` (`frontend/src/lib/cost-views.ts:81-109`) and the
  topbar pill renders **"Not calibrated — generic defaults"** (`glass-box/calibration.tsx:92`).
- Clicking "Swap shop" in the live UI just toasts: *"Shop calibration through the API is a build gap —
  the engine binds a shop per call."* (`workspace/PartWorkspace.tsx:391-396`).

The CLI *does* calibrate (`cli --shop "Midwest Precision CNC"` re-costs to `$7/kg`, `$52/hr`,
overhead 1.15, utilization 0.8 — and notably pushes that part's cost *up*, not down). The capability
is real in the engine and invisible in the product. The marketing `$44/$110/$35 across shops` story is
told entirely with a **hardcoded fixture** (`components/marketing/data.ts:30-181`), not a live run.

### 1.2 Routing recommends a process its own DFM check hard-fails — in the same panel.
The Routing & DFM lens (`workspace/RoutingDfmView.tsx`) is the manufacturing engineer's trust object.
On the fuel-pump-holder part it renders, as a big display headline, **"Geometric routing → CNC turning,
archetype: rotational, confidence 0.80"** with a `MEASURED rotational: yes` chip
(`glass-box/routing.tsx:40-83`) — and directly below it the DFM matrix flags that *same* `cnc_turning`
as **`fail` (score 0.0)** with the blocker *"Part lacks rotational symmetry (eigenvalue ratios: 0.69,
0.76). Required for cnc_turning."* The routing reasoning even says *"A round metal part is rarely
powder-bed printed"* while the actual decision is **Make by MJF (powder bed, polymer)**.

This is **systematic, not a one-off** — reproduced on 4 of 5 printed ECU/bracket/enclosure parts I
ran (fuel-pump-holder, `macchina_m2_M2R3_CASE_TOP_UTD`, `amrikarisma_Mazduino_LITE_TOP`). Root cause:
two different definitions of "rotational" that disagree:
- Routing uses **bounding-box cross-section squareness**: `roundness = min(c1,c2)/max(c1,c2)`,
  fires when `>= 0.80` (`backend/src/costing/routing.py:41-47`). An 85×88×23 mm rectangular enclosure
  lid scores `85/88 = 0.97` → "rotational". It conflates *square* with *round*.
- DFM uses **inertia-tensor eigenvalue ratios** (`backend/src/analysis/processes/checks.py:553-575`),
  which correctly rejects it.

This is the direct analogue of the "sheet-metal bug just fixed" — still live for turning. A mfg
engineer would lose trust in the routing on the first part.

### 1.3 "Override → re-runs" is false in the live app.
The glass-box driver row button literally reads **"Override — re-tags USER, re-runs"**
(`glass-box/driver-breakdown.tsx:90`) and the assumptions panel says "override → re-tags USER"
(`workspace/GlassBoxView.tsx:167`). The handlers do **not** re-run anything — they relabel the value
client-side and toast: *"Server re-cost on driver overrides is a build gap"* / *"Server re-cost on
shop-rate overrides is a build gap"* (`PartWorkspace.tsx:189-206`). "Save as scenario" toasts
*"persisted, versioned scenarios are a build gap"* (`PartWorkspace.tsx:208-210`). So the central
"open the model and edit it" interaction is cosmetic — the number never moves.

### What is genuinely trustworthy here (no-bias the other way)
- **Σ line-items = unit cost** is shown as a live coherence check and turns red if it ever breaks
  (`driver-breakdown.tsx:121-147`). Verified `Σ = $64.63` on the live API.
- **Confidence intervals DO flow through the API** (the "build gap" fallback text in
  `CostDecisionView.tsx:284` / `GlassBoxView.tsx:185` is a defensive branch that does not fire):
  live estimates carry `confidence{low,high,half_width_pct, validated:false, n_samples:0,
  label:"assumption-based, not yet validated"}`. The honesty is real and consistent.
- **Provenance tags are real and per-driver** with verbatim source strings (`MEASURED hull volume
  347.87 cm³ × … $5/kg (DEFAULT)`), straight from the engine.
- **Broken geometry → clean structured 400 `GEOMETRY_INVALID`**, not a 500 (`routes.py:566-578`).
- **IP-local is real**: the engine prints `[wall-clock 0.33s · IP-local, zero network calls]`.

---

## AXIS 2 — CAPABILITY / DEPTH

### 2.1 Absolute cost is ±40–60% and explicitly unvalidated (`n_samples: 0`).
Every estimate ships `validated:false`, `±40–60%`, *"assumption-based, not yet validated … no ground
truth yet"* (live API + CLI). This is stated honestly, but it means the **dollar is not yet a
buyable number** — only the make-vs-buy *direction* and crossover qty are claimed robust. Fine as a
wedge; not fine if a buyer expects a quote.

### 2.2 The live "edit & re-run" loop is 5 coarse dropdowns, not "every assumption."
The only inputs that actually re-cost through the API are qty, material_class, region, complexity,
cavities (`cost/CostOptionsForm.tsx:24-30`, `CostDecisionView.tsx:232-251`). The CLI's real levers —
`--labor-rate`, `--margin`, `--set machine_rate.SLS=25`, `--tooling`, `--shop` — are **not exposed in
the web form**. "Every assumption is editable" (homepage role-card, `page.tsx:278-282`) reduces in the
product to 5 dropdowns plus non-functional per-driver overrides (1.3).

### 2.3 Material class is a manual input, not inferred — and silently mis-routes.
`material_class` defaults to `polymer` and is a dropdown the user must set
(`CostOptionsForm.tsx:88-105`). The engine never infers it from geometry, so the routing prose says
*"A round **metal** part…"* for a clearly-plastic ECU bracket because someone has to tell it the class.
Pick wrong and the whole model re-costs wrong with no warning.

### 2.4 The decision slider interpolates; it doesn't re-run the engine.
The quantity slider "re-costs instantly (client-side, from the report's own fitted curves)"
(`CostDecisionView.tsx:6-8`, `deriveBreakeven`). Reasonable, but the smooth qty→price is a fitted
line between 2 costed points, not engine truth at each qty — worth knowing when a number is defended.

### Genuinely deep / real
- The engine scores **18 processes** in 0.33 s with a real DFM feasibility matrix, real geometry
  (volume/bbox/watertight/face-count, `MEASURED`), per-process cycle-time/material/setup decomposition,
  and a make-vs-buy crossover with tooling amortization. This is not a toy.
- The 3D viewer is **real three.js** (`@react-three/fiber` + `STLLoader`, `ui/cad-viewer.tsx`) with
  face highlighting and click-to-select-issue two-way linking — a genuine, polished capability.
- STEP (via gmsh) and STL both parse; API-key management (create/rotate/revoke, reveal-once) is real
  (`settings/developer/page.tsx`).

---

## AXIS 3 — POLISH / CREDIBILITY

### 3.1 Internal dev surfaces ship in the customer sidebar.
The production nav (`ui/sidebar.tsx:20-44`) lists **"Parts (Label)"** — a corpus ground-truth
*annotation tool* (`label/page.tsx`, an internal data-ops surface) — and **"Design system"** — a
component showcase whose own header calls it *"the build proof"* (`design-system/page.tsx:1-9`).
A logged-in customer sees both next to Cost/Analyze. Both return 200 and are one click away. This is
the clearest "this is a dev build, not a product" tell.

### 3.2 The marketing site never runs the engine — it renders a static fixture, captioned as live.
The hero (`page.tsx:82-89`) sits under the caption *"Real output · object analyzed by the cost-truth
engine"*, and `/method` says *"the real product, rendering the engine's actual output … not
screenshots"* (`method/page.tsx:57-61`). In fact every marketing number is a **hardcoded constant** in
`components/marketing/data.ts` (`unit_cost_usd: 14.14`, `crossoverQty: 1962`), captured once from a
part `bracket_v3.stl` that **isn't in the corpus**. The same engine on a real part returns `$64.63`.
There is no live "try it" on the marketing site — you must sign up. The numbers were really generated,
but the page is static and the caption oversells it.

### 3.3 The marketing fixture embeds the §1.2 contradiction.
`data.ts:126-134` ships `recommended_process: "cnc_turning"`, reasoning *"round metal … rarely
powder-bed printed"*, while the hero headline is *"Make by MJF (PP)"* (`page.tsx:113-117`). The flagship
example contradicts itself on the home page.

### 3.4 Aspirational trust claims stated in present-ish tense.
"On the ITAR / AS9100 path", "Built for regulated hardware" (`page.tsx:225-256`). It's a local-dev
build — no cloud deploy, no SOC2/ITAR, auth is email+password against a local Postgres. The copy says
"designed to / on the path", which is defensible, but a security reviewer will read the section as
bigger than the artifact.

### Polish that is genuinely good
- The design language is coherent and not a bootstrap-admin template: provenance dots, hatched
  confidence bands, role-lens, the collapsible driver rows with inline verbatim sources
  (`driver-breakdown.tsx`) read like considered product, not a wall of raw numbers.
- Real empty / error / loading states exist and are wired (`ui/empty-state.tsx`, `ui/error-state.tsx`,
  `LoadingPane` in `PartWorkspace.tsx`); the cold-start dropzone and the GEOMETRY_INVALID repair card
  are handled, not crashes.

---

## AXIS 4 — UX / EASE

### 4.1 The honest "build gap" toasts, while admirable, are all over the primary loop.
A user who actually drives the glass box (the differentiator) hits *"build gap"* on override, on
driver override, on save-scenario, and on shop-swap — four of the most natural actions
(`PartWorkspace.tsx:189-210, 391-396`). Internally honest; externally it reads as a demo where the
interesting buttons don't work.

### 4.2 One-drop, role-lens flow is genuinely good.
A single CAD drop runs cost + DFM together, the part stays in a persistent 3D rail, and the Role Lens
sets the landing tab without walling anything off (`PartWorkspace.tsx:407-563`). Decision-first for
the design engineer, glass-box-first for the cost engineer — this is the right shape and it works.

### 4.3 The working re-cost loop is real but quietly shallow.
Changing qty/material/region/complexity/cavities and hitting "Re-cost with these inputs" does a real
round-trip to the engine (`CostDecisionView.tsx:241-249`). It works — but a user expecting to edit
"labor_rate" or "machine_rate" (the things the glass box shows) can't, and isn't told why until they
click and get a toast.

---

## Bottom line per axis
- **Correctness/trust:** engine-level honesty (provenance, Σ-check, confidence, IP-local) is real and
  good; product-level it ships a self-contradicting router (1.2) and a headline wedge that isn't wired
  (1.1) and edit-affordances that lie (1.3).
- **Capability/depth:** the engine is real and fast (18 processes, real DFM, crossover); the dollar is
  ±40-60% unvalidated and the live editing surface is far thinner than the CLI.
- **Polish/credibility:** the design language is real; the dev surfaces in nav (3.1), the static-but-
  "live"-captioned marketing (3.2-3.3), and the self-contradicting hero (3.3) undercut it.
- **UX/ease:** the one-drop role-lens flow is the right shape and works; the headline interactions in
  the glass box currently toast "build gap."

The buyable core is the **glass-box engine** (provenance + Σ-check + confidence honesty + IP-local +
make-vs-buy). The work to be *real software* is: wire shop calibration into the API, fix the
rotational router (or stop headlining a DFM-failing process), make override actually re-cost, and pull
the label/design-system tools out of the customer nav.

# CadVerify — THE LIVING INSTRUMENT (interaction spec + build note)

**Role:** Principal Product Designer + Staff Frontend Engineer. **Date:** 2026-06-30.
**Status:** Built. Replaces the tabbed `PartWorkspace` as the core part experience.
**Identity source of truth:** `outputs/design/identity-ramp-mercury.md` (Datum Blue `#0E66B3`,
Archivo Expanded monumental numbers, Geist Mono evidence, blueprint-twilight instrument surface).

---

## 0. The concept, in three lines

A CAD part dropped onto a dark instrument surface and **read like a live gauge, not a report**: the
part floats in real 3D at the center of gravity, the manufacturing decision orbits it as monumental
live readouts, and a **quantity scrubber** runs the whole length of the panel. Drag the scrubber and
the recommended process **flips** (additive → CNC → mold), the cost/unit number **morphs**, and the
make-vs-buy curve under your thumb lights the crossover — all client-side, zero server roundtrip, so it
feels alive. A **shop dial** and **assumption knobs** recalibrate the entire decision live; the
glass-box drivers are one calm reveal away. The wow is tactile: *you hold the decision and move it.*

The enemy was "another dashboard with tabs and tables." There are **no tabs**. One canvas, one part,
one decision you manipulate with your hands.

---

## 1. Direction before components — why this, for whom

For the sourcing lead / manufacturing engineer who already distrusts black-box quote tools: the
instrument makes the cost *move under their hand* so they can feel where the decision changes, and
every number it shows can be traced to its driver. It is a **calibrated instrument on the shop floor**,
not a SaaS dashboard. Boldness is spent in exactly one place — the scrubber + the monumental number —
and everything else stays quiet (the identity's discipline).

The single risk taken: the cost-vs-quantity curve is **the scrubber itself** — the draggable handle
rides directly on the lower-cost envelope, and the process the handle is sitting on is the process the
big readout names. The chart is not a separate panel you read; it is the control you hold.

---

## 2. The signature interaction (the 30-second wow)

**The Quantity Scrubber** (`QuantityScrubber.tsx`) — a full-width SVG instrument, log quantity on x,
$/unit on y, one graphite curve per costed process, the **cheapest-at-this-quantity curve lit in Datum
blue**. A vertical datum line + a dot that **travels along the lit curve** is the handle.

- **Drag anywhere on the plot** (pointer) or use **arrow keys** (focusable, `role="slider"`): quantity
  re-maps log 1 → 100k instantly.
- As the lit envelope's argmin process changes, the **lit curve hands off** to the new process and the
  readout's process name + monumental cost **flip together** — driven by `recommendAt()` /
  `unitCostAt()` from `lib/breakeven.ts` (curves fitted from the report's OWN reported unit costs, so
  the curve passes exactly through the engine's numbers — no invented figures, no server call per drag).
- **Crossovers are lit**: every quantity where the recommended process changes draws a Datum datum-tick
  + label; the engine's authoritative `crossover_qty` is a labeled witness line.
- Motion discipline: curves draw-in **once** on mount (stroke reveal); during scrub the handle moves and
  the number morphs — the scrub *is* the motion, nothing else animates. `prefers-reduced-motion` cuts
  the draw-in and snaps values.

## 3. The decision, rendered as readouts (around the part)

**DecisionReadout.tsx** — the two number voices, kept strict:
- The **answer** is monumental: `$14.14` `/unit` in Archivo Expanded (`.cv-readout-hero`), tabular,
  with `$`/`/unit` riding small in muted. Re-keys + settles briefly on a process flip (a caliper coming
  to rest), never on every digit.
- Recommended **process** + DFM-ready / needs-redesign verdict badge, **lead time**, and the **at
  quantity** the scrubber currently holds.
- The **confidence band** sits under the number drawn with the assumption **hatch** — honest by
  construction: `validated:false`, `n=0`, label rendered verbatim ("assumption-based, not yet
  validated"). Never a fabricated ±X%.
- A row of **provenance dots** (MEASURED ● / SHOP ● / USER ● / DEFAULT ○) proves the figure is grounded;
  the gaps stay visible on purpose.
- **"if redesigned"** honesty banner when the tooling route currently fails DFM — never asserts a
  process the part fails today.

## 4. The recalibration controls (live)

- **Shop dial** (`InstrumentControls.tsx`, from `GET /shops`) — a segmented dial; selecting a shop
  re-costs with that shop's real rates (`opts.shop`), **debounced** ~280ms. The readout keeps its old
  value and shows a quiet "recalibrating" shimmer, then settles to the SHOP-tagged number.
- **Assumption knobs** — material class, region, and labor rate. Material/region re-cost via
  `CostOptions`; labor rate threads the real **overrides** API (`{ labor_rate }`) and re-tags touched
  drivers **USER**. Same debounce + settle. The knob value updates optimistically; the answer settles
  when the server returns.

## 5. Glass box on demand + DFM on the geometry

- **Ask why → Glass box drawer** (`GlassBoxDrawer.tsx`): a calm panel slides up over the scrubber
  showing `DriverBreakdown` for the *currently recommended* estimate at the snapped quantity — every
  driver provenance-tagged + sourced, Σ line-items = unit cost, each row drillable and **overridable**
  (real re-cost, USER re-tag). Drivers reveal on demand; they are never dumped.
- **DFM flags ride on the part**: `flattenIssues()` → a compact flag rail; **hovering a flag highlights
  its faces** on the 3D part (and ghosts the rest); clicking pins it. Clicking a face on the part
  selects the matching flag. (Reuses `cad-viewer` face-link.)

## 6. States (all designed)

- **Empty** — the drop zone *is* the canvas: dark blueprint-twilight field (`.cv-hero-field` grid),
  tick eyebrow, "Drop a part. Watch the decision resolve." An invitation to act.
- **Loading ("figuring it out")** — the part renders immediately from the file while the panel runs a
  stepped resolve sequence (measuring geometry → routing process → costing across processes → fitting
  the curve) that dissolves into the live readout when the report lands. Feels like intelligence
  happening, not a spinner.
- **Error / GEOMETRY_INVALID** — an instrument-styled card: the engine's reason + the measured geometry
  it rejected (volume / watertight / faces), and "Try another part." Honest, not apologetic.
- **Hover / focus / disabled** — visible Datum focus rings, scrubber keyboard control, recalibrating
  disables knobs with a shimmer (never a hard block).

## 7. Identity fidelity

Blueprint-twilight instrument surface (`.cv-twilight` locks the dark semantic vars for the panel
subtree even in light OS mode), Datum Blue as the only chromatic voice (the lit curve, the handle, the
focus ring, the hero datum marker), Archivo Expanded monumental answer + Geist Mono evidence,
instrument bezel (`.cv-faceplate` / `.cv-bezel`) not stock shadows, gauge-needle motion. Status colors
(pass/warn/fail) stay in their own lane; Datum never signals state.

---

## 8. What is live (real engine, not a mock)

- **Quantity scrub** — fully live, client-side, instant. Flips process, morphs cost, lights crossovers.
- **Shop dial** — live, debounced real `POST /validate/cost` with `shop`.
- **Assumption knobs** (material / region / labor rate) — live, debounced real re-cost; labor rate via
  the overrides API (USER re-tag).
- **Glass box** — real `report_to_dict` drivers, provenance, Σ-coherence, real override re-cost.
- **DFM ↔ geometry** — real `validate` issues highlighted on the real STL mesh, two-way linked.
- Numbers are the engine's; confidence is honest (`n=0`, not yet validated); no fabricated accuracy.
- **Stub (honest):** "ask why" opens the real glass box (that *is* the why); a thin "ask the model"
  affordance is labeled as not-yet-built, per brief — no over-built AI this round.

## 9. How to view it

- Route: **`/cost`** (lands focused on the decision) or **`/analyze`** (lands with the DFM rail open).
  Both now render the Living Instrument; the tabbed workspace is retired from these entry points.
- Log in with **nazeem+livetest@anodeadvisory.com** / **Passw0rd123**.
- Drop an `.stl` (3D + scrub + glass box all live). `.step/.stp` cost the same but show a "STEP preview
  requires backend conversion" placeholder in the viewer (existing, honest behavior).
- Drag the scrubber along the bottom; switch the shop dial top-right; turn a knob; click "Ask why" to
  open the glass box; hover a DFM flag to light the part.

## 10. Build proof

- `npx tsc --noEmit` → **exit 0** (green).
- `npm run build` (Next 16.2.3 / Turbopack) → **exit 0**; `✓ Compiled successfully`, TypeScript checked,
  18/18 static pages generated. `/cost` and `/analyze` both build as dynamic (ƒ) server-rendered routes.
- Runtime gate verified: `/cost` → 307 (→ /login), `/analyze` → 307, `/login` → 200 (auth gate intact).
- **Self-critique screenshot (headless Chrome, fixture-seeded preview, then fully reverted):** the loaded
  instrument renders as intended — the part floats on the blueprint-twilight grid, the monumental
  `$11.93 /unit` reads as the hero in Archivo Expanded with the hatched "not yet validated (n=0)" band, the
  recalibration knobs sit calm on the right, and the full-width scrubber draws the lit Datum envelope + the
  graphite alternatives with the handle dot riding the curve (live cost tag, quantity pill, crossover witness
  line). Confirmed it does NOT read as a tabbed dashboard. The temporary `demo` seam, preview route, and demo
  STL were removed; final tsc + build re-run green with zero leftover references.

### Files
- New: `frontend/src/components/instrument/LivingInstrument.tsx` (orchestrator + all states),
  `QuantityScrubber.tsx` (the signature SVG scrubber), `DecisionReadout.tsx` (monumental readout cluster),
  `InstrumentControls.tsx` (shop dial + assumption knobs), `GlassBoxDrawer.tsx` (on-demand drivers).
- Repointed: `frontend/src/app/(app)/cost/page.tsx` → `<LivingInstrument focus="decision" />`;
  `frontend/src/app/(app)/analyze/page.tsx` → `<LivingInstrument focus="dfm" />`.
- Edited (additive): `frontend/src/components/ui/cad-viewer.tsx` — added a `surface="instrument"` variant so
  the part floats on the twilight working canvas (light variant unchanged).
- Reused unchanged: `lib/breakeven.ts`, `lib/api.ts`, `lib/cost-views.ts`, the glass-box atoms
  (provenance / confidence / driver-breakdown), `flattenIssues`, the design tokens in `globals.css`.
- The tabbed `PartWorkspace` and `CostDecisionView` remain in the tree (still compile) but no longer back
  `/cost` or `/analyze`.

_No git commit (per brief)._

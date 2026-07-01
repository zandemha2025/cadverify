# CadVerify — Structural Redesign: "The full-bleed instrument, not a dashboard"

**Role:** Principal Product Designer. **Round:** full structural redesign (not a reskin).
**Identity kept:** Datum Blue, Archivo Expanded monumental numbers, Geist Mono evidence, blueprint-twilight,
machined faceplate soul (per `identity-ramp-mercury.md`). **What changed:** the LAYOUT + INTERACTION MODEL.

The app used to read as a generic SaaS dashboard: a fat left admin sidebar (Analyze/Cost/Batch/History/
Developer) + a dashed-border dropzone card floating in a padded content panel. That skeleton is gone. The core
is now a full-bleed instrument you operate, with everything secondary tucked one keystroke away.

---

## 1. The new shell / IA — the sidebar is dead

**Killed:** `ui/sidebar.tsx`, `ui/topbar.tsx`, `ui/nav-item.tsx` (deleted). The persistent 256px admin rail and
its breadcrumb topbar no longer exist.

**Replaced with two things:**

- **A slim top strip** (`ui/top-strip.tsx`, one row, `--topbar-h`): `[ datum-crosshair wordmark ] ··· [ the
  loaded part's identity ] ··· [ ⌘K ] [ theme ] [ account ]`. The middle is **contextual, not admin nav** — empty
  when nothing is loaded; when a part is loaded it shows the part's name, its measured facts (vol / bbox / faces /
  watertight), the DFM verdict badge, and a "New part" reset. The chrome describes what you're *holding*, not a
  list of destinations. This is wired through a new `instrument/instrument-chrome.tsx` context that the instrument
  **publishes** its part identity into (cleared on reset / navigation).
- **A ⌘K command palette** (`ui/command-palette.tsx`, built on the installed Radix Dialog — no new dependency):
  the secondary destinations that used to be sidebar rows (Batch, History, Developer, API docs, plus dev-only
  Label / Design system) now live here, with a live filter, arrow-key nav, Enter to run, Esc to close, and
  theme/sign-out actions. Open with ⌘K/Ctrl-K anywhere or the "Jump to…" button in the strip. Dev-only tools stay
  gated behind the existing `dev-flag`.

`app-shell.tsx` was rewritten: providers (chrome + palette) → slim strip → a single `<main>`. The core routes
(`/cost`, `/analyze`) render **full-bleed** (no padded panel, no max-width); secondary "document" routes keep a
comfortable reading container so Batch/History/Developer/docs work unchanged this round. Public/share pages use
their own `public-chrome` and were untouched.

## 2. The intake — the dashed dropzone card is dead

**Killed:** the `<Dropzone>` card in the core intake (the "Drag and drop or click to upload" dashed box).

**Replaced with a full-bleed immersive drop surface** (`LivingInstrument` empty state): the **entire workspace is
the drop target**. A blueprint-twilight field fills the viewport; a faint **ghost machined part** (new
`instrument/GhostPart.tsx` — a flange with bore, bolt circle, and dimension callouts drawn in Datum strokes) sits
as the idle centerpiece. Drag a file anywhere over the surface and the instrument **arms itself**: the field gets
a Datum inset ring, the ghost part lights up and a measurement sweep runs across it, and a "Release to load"
affordance appears. A monumental Archivo-Expanded invitation ("Drop a part. Watch the decision resolve.") anchors
bottom-left with one confident CTA. No little box in the middle of a page.

## 3. The loaded state — one composed INSTRUMENT, not two columns

Gone is the part-left / data-right dashboard grid. The loaded view is a **HUD composition**:

- **The machined part commands the whole canvas** — `cad-viewer.tsx` (material/lighting/studio rig kept exactly)
  is the full-bleed background layer (`absolute inset-0`), edge-to-edge, with a soft corner vignette so the
  floating readouts seat legibly. You orbit the part directly in the open center.
- **The decision reads as a floating HUD panel, top-left** — a frosted, backdrop-blurred instrument panel holding
  the make-by process, the **monumental $/unit** (Archivo Expanded), lead time, the crossover sentence, the honest
  hatched confidence band, and the provenance ledger. Recalibrate expands *inside* this panel (progressive
  disclosure); "Ask why" opens the glass-box drawer.
- **The quantity scrubber is a real control seated along the bottom edge** — full-width instrument rail; drag the
  dot and the recommended process flips live from `lib/breakeven`'s fitted curves (zero server roundtrip), exactly
  as before.
- **Shop / material / region / labor stay tucked** behind Recalibrate (real debounced re-cost, USER/SHOP
  provenance re-tag intact).
- **DFM floats in its own collapsible panel, top-right** — the severity summary as a chip; expanding reveals the
  rows, and hovering/selecting still **highlights faces ON the geometry** (two-way `onFaceClick` link kept).
- The **glass box** remains a bottom drawer revealed on demand.

Legibility/accessibility: panels are frosted dark glass (`rgba(10,17,30,.86)` + blur + bezel) hugging the corners
so the centered part is never obscured; keyboard focus rings, the scrubber's `role="slider"` + arrow keys, reduced
motion, and the real CTA button for the click-anywhere intake are all preserved.

## 4. Functionality & states — all preserved

Upload, the real cost/DFM engine calls, the scrubber, shop dial/knobs, glass-box override re-cost, DFM
highlighting, and session-auth gating all unchanged. Every state still renders — **empty** (full-bleed intake),
**resolving** (the step sequence, in the decision panel), **loaded** (HUD), **geometry-invalid** (rejected panel),
and **cost/DFM error** (inline, non-blocking). Whole-surface drag-to-replace works in the loaded state too.

## 5. Build proof

- `npx tsc --noEmit` → **clean (exit 0)**.
- `npm run build` → **✓ Compiled successfully**; all 18 app routes generated (incl. `/analyze`, `/cost`, `/batch`,
  `/history`, `/settings/developer`, `/design-system`, `/docs`). Auth and the engine are untouched. No server
  started; no commit made.

**Files added:** `instrument/instrument-chrome.tsx`, `instrument/GhostPart.tsx`, `ui/command-palette.tsx`,
`ui/top-strip.tsx`. **Rewritten:** `ui/app-shell.tsx`, `instrument/LivingInstrument.tsx`. **Deleted:**
`ui/sidebar.tsx`, `ui/topbar.tsx`, `ui/nav-item.tsx`.

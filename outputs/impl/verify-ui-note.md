# Builder note — Product Verify UI (feat/verify-ui)

**What**: the founder-approved `Product - Verify.dc.html` light instrument, recreated
in the production Next.js stack and wired to the REAL engine, behind
`NEXT_PUBLIC_VERIFY_UI` (default OFF). Mounted at `/verify` in a NEW route group
`src/app/(verify)/` — separate from `(app)` so it does not inherit the dark
enterprise AppShell (this surface is its own rail + top bar).

## Flag / byte-identical guarantee
- `src/lib/verify-flag.ts` → `VERIFY_UI` (compile-time, from `NEXT_PUBLIC_VERIFY_UI`).
- `src/app/(verify)/layout.tsx` calls `notFound()` when the flag is off, BEFORE any
  render, then `verifySession()` (same hard gate as the rest of the platform).
- Flag-off is byte-identical: the ONLY existing file touched is
  `frontend/package.json` (one-line extension of the `--test` list). No globals.css,
  no shared component, no existing route changed. Everything else is new files under
  `src/app/(verify)/`, `src/components/verify/`, `src/lib/verify/`.
- The register is theme-independent (the app is dark-first; `.dark` on `<html>`).
  All Verify styling is explicit hex per DESIGN-DECISIONS (`src/lib/verify/tokens.ts`),
  never the Tailwind semantic tokens — so the dark theme can't bleed in.

## KEY FINDING — makeability `verification` block is NOT surfaced on `dev`
`src/costing/makeability.py` (`verify_part`, the verdict lattice) is real, but it is
NOT wired into `/validate` or `/validate/cost` on `dev` (grep: no import of
`makeability` / `verify_part` in `analysis_service` / `cost_service` / `report.py` /
`routes.py`'s cost path). So the live API carries NO top-level `verification` block.

Per the honesty rules I render the **honest unknown / feature state** for the
makeability gates (envelope, materials-survival), NEVER a fabricated
makeable/not-makeable verdict:
- Envelope (step 1): if inventory empty → "No machines declared" empty state; if
  present → the declared floor listed (● USER) with an explicit "per-machine fit is
  decided by the makeability verification — ENGINE BLOCK PENDING; no fit is faked".
- Materials (step 2): real `material_class` from the cost report + honest note that
  NACE/HDT survival filtering is the makeability feature, "NOT SURFACED THIS BUILD".
- `run.ts` reads a `verification` key off either response if a future build adds one
  and renders it verbatim; until then it's null → the honest state above.
- Env door: env is a real captured declaration + drives the stage rim reaction, but
  `/validate/cost` has no env parameter on this build, so it is NEVER used to
  fabricate a changed cost (documented in `run.ts`).

## Wiring (every rendered number is real or withheld)
- **Verify walk** (`verify-screen.tsx`) — `runVerification()` (`lib/verify/run.ts`):
  - `POST /api/proxy/validate` → routing + DFM (process_scores, best_process,
    priority_fixes) → step 3 "process physics", overall DFM verdict in the banner.
  - `POST /api/proxy/validate/cost` (posted directly so `owned_processes` — the org's
    declared floor — can be sent → marginal costing) → geometry (● MEASURED bbox/vol),
    drivers with provenance + verbatim `source` (step 4 + tap-to-disclose), estimates
    by qty + `decision.crossover_qty` (step 5 scrub), confidence band
    (hatched/solid from `confidence.validated`, tick at the real point fraction).
  - `GET /api/proxy/machine-inventory` → the declared floor (step 1) + owned processes.
  - Quantity scrub interpolates a log ladder and SNAPS to the engine's real computed
    quantities (`nearestQty`) — never an off-ladder invented cost.
  - Negative path: `/validate/cost` 400 GEOMETRY_INVALID → the walk renders step 1
    then a "THE WALK STOPS AT THE FAILED GATE" card and renders NOTHING downstream.
  - First-run: no upload → the honest "Drop a part to begin the walk" empty state
    (no pre-baked $14.14 fixture; that is design fixture, not app data).
- **Machines** (`machines-screen.tsx`) — real CRUD on `/machine-inventory`:
  list / create (add-machine modal, new machines ● USER) / detail / delete + CSV
  import (`/machine-inventory/import`, honest partial-success summary). Empty → the
  "Declare your floor" state.
- **Records** (`records-screen.tsx`) — real `GET /cost-decisions` list + `{id}` detail
  (make-now route, crossover, drivers with provenance). Empty → honest state. Shared
  read-only record view is time-boxed IN DEVELOPMENT.
- **Home** (`home-screen.tsx`) — drop zone → verify flow; KPIs are REAL counts
  (records, machines) or withheld ("—"); in-flight = the org's real recent records.
- **3D stage** (`stage.tsx` + `stage-canvas.tsx`) — @react-three/fiber, ssr:false
  (same pattern as the app's CadViewer). Renders a dropped STL from its real geometry;
  STEP (unparseable in-browser) falls back to a wireframe box sized to the engine's
  MEASURED bbox — an honest envelope, not a fake shape. X-ray toggle; rim warms when
  the world is hostile; slow auto-orbit during the compute.

## Stubbed as honest IN DEVELOPMENT (`stub-screens.tsx`) — visible, labelled, never fake
catalog · compare · programs · triage · calibration & truth · acquisition modal ·
notifications · ⌘K command palette (navigational only; scripted use-cases + engine
asks not faked). Each states its real backend seam.

## Provenance / honesty encodings
`tokens.ts` carries the canonical light provenance pair (MEASURED/SHOP/USER/DEFAULT +
○ MODEL for computed hours). `primitives.tsx`: filled dot = grounded, hollow = MODEL/
DEFAULT; hatched band = assumption (n=0), solid = validated — driven by the engine's
`confidence.validated`, rendered VERBATIM (`confidence.label`), never a fabricated ±%.

## Gates
- `npx tsc --noEmit` — clean (exit 0).
- `npm test` — 174 pass / 0 fail (168 existing + 6 new `src/lib/verify/derive.test.ts`,
  added to the `--test` list; JSON validated with `python3 -c "import json;…"`).
- `npx next build --webpack` — exit 0; `/verify` compiled as `ƒ` (dynamic). (Turbopack
  panics on symlinked node_modules → webpack, per the brief.)
- `npx eslint` on the new tree — clean.

## Notes / follow-ups
- The biggest unlock is backend: surface `verify_part`'s `verification` block on
  `/validate` (or `/validate/cost`). The UI already reads + renders it verbatim; the
  moment it appears, the envelope/materials gates flip from honest-pending to a real
  per-route makeability verdict with zero UI change.
- `owned_processes` is filtered to known engine ids so an odd machine process can't
  400 the whole cost call (unknown → fully-loaded fallback, still honest).
- `/validate` + `/validate/cost` require the `analyst` role; a `viewer` session gets
  403 → surfaced honestly as "withheld — unavailable", never faked.

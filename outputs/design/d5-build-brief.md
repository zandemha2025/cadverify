# D5 — Frontend Build Brief (the real product, not a demo)

**Status:** the build instruction for the production frontend. Canon: `outputs/design/product-definition.md` (D1) + the approved D2 structure + D4 interactions (prototype files archived in session scratchpad; this doc is self-sufficient). Standing gates apply: findings-only-in-a-tab FAILS · any UI element without a real engine field FAILS · honest "coming" states, never stubs.

## Stack realities (build WITH them, not around them)
- Next.js 16 App Router · Tailwind v4 `@theme` token indirection in `globals.css` (the swap point — purpose-built) · `node --test` suites · flags via `NEXT_PUBLIC_*`.
- **`components/ui/cad-viewer.tsx` already does the hard part**: real three.js part rendering + per-vertex face highlighting + `onFaceClick` → issue lookup. The part hero STAGES this existing component; nobody rewrites it.
- Pure logic survives untouched: `lib/breakeven` `lib/cost-views` `lib/dfm-scope` `lib/cost-decision` `lib/status`.
- Real data only: `/api/v1/validate` response (`Issue{severity,affected_faces,region_center,measured_value,required_value,fix_suggestion}`), `report_to_dict` (drivers w/ provenance+source), history/cost-decisions endpoints. The Findings-API gaps (structured citations, untruncated faces, thickness map) are backend items — UI renders what exists and states what doesn't.

## Design tokens (the register, productionized)
- **Surfaces (stage ramp):** `--stage-0 #0C0E10 · --stage-1 #14171A · --panel rgba(16,19,22,.78)+blur · --line #252A2F`. Light mode: DEFERRED (dark-viewport is native to CAD users; revisit post-v1).
- **Text:** `#F4F2EE / #A6ACAF / #61686C` — warm white, never pure.
- **Semantic color (each means one thing, nowhere else):** cost/molten `#F97316→#FFC06A` · severity ERROR `#E05252` / WARN `#E5A83B` / INFO `#8FA0A6` · VALIDATED brass `#CFA84E` only · provenance MEASURED `#4FB3BF` / SHOP `#D08A4C` / USER `#9D8CFF` / DEFAULT hollow outline `#78828A`. Grammar: filled=grounded · hollow=guess · hatched=unvalidated · solid=validated.
- **Type (real faces, self-hosted via npm `@fontsource-variable/*` — no CDN):** UI+display `Instrument Sans Variable` (tight tracking ≥28px); numerals/meta `JetBrains Mono Variable` with `tnum` everywhere digits column. Retire system stand-ins.
- **Motion:** springs `strike cubic-bezier(.16,1,.3,1) 340ms` · `settle 520ms` · productive default 120–200ms. **TEMPO system:** `showcase` (full choreography — first session, demo mode, `?tempo=showcase`) vs `working` (durations ×0.1, no compute theater) — a context provider; default working after first visit (localStorage); `prefers-reduced-motion` collapses everything.

## Build order (PR-sized, each: builder → verifiers → my gate)
1. **FE-1 `feat/stage-tokens`** — re-token `globals.css` values (names stay), install fonts, `TempoProvider` + `useTempo`, motion primitives (`<Rise>`, staggered list), retune cad-viewer lighting/severity hexes to the register. Flag `NEXT_PUBLIC_STAGE_UI` (default off until FE-3).
2. **FE-2 `feat/part-hero`** — the retable on the REAL data path: `/analyze`+`/cost` render Inspection|Decision co-primary columns around `CadViewer`; findings list from real Issues (scoped via `dfm-scope`), 4 finding classes (DFM + provenance-caveat + confidence + fragility — the latter three derived from the real report client-side); two-way face↔finding via existing wiring, promoted out of the tab; verdict + odometer + crossover chart (`lib/breakeven`); glass box + process matrix as slide panels. Reveal order = compute order in showcase; instant in working.
3. **FE-3 `feat/three-doors`** — landing router (`ROLES` graduates from toggle), door chooser first-run, part-first landing w/ dropzone, working-tempo default post-first-session. Flag flips on.
4. **FE-4 `feat/catalog-door`** — the cost-engineer grid over real history/cost-decisions (posture bars from real driver provenance, findings counts, blocked-withheld). Row → part hero.
5. **FE-5 `feat/portfolio-door`** — exception-first queue over the real DFM batch aggregates; savings queue = honest coming-state (W3).
Each PR ships with: `node --test` coverage for new logic, e2e smoke updated, `tsc` clean, Turbopack build green (main tree), reduced-motion + keyboard paths.

## Verifier lenses per PR (in addition to suite-green)
A **craft rubric** — squint test; one-line slop test; accent rationing; type discipline (tnum, tracking); would a Linear engineer respect this code+UI. B **honesty** — every element binds to a real field (name it); no fake affordances; coming-states truthful. C **product** — the standing gates + persona 30-second test for the door being built.

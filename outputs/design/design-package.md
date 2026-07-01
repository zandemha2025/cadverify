# CadVerify — Design Package (assembled)

**Program:** 7-agent audience-driven design program · workflow wjyuip8rq · **PASSED audit, 0 repairs** ·
orchestrator independently verified (typecheck clean, all surfaces serve 200, fresh backend emits routing+confidence).

## 1. Thesis (the spine, now built — not prose)
- **Glass-box is the hero** — every number carries provenance (filled marker = grounded in *your* reality: MEASURED/SHOP/USER; hollow ring = generic DEFAULT guess, gap visible), drivers sum to the unit cost (Σ row shown), every assumption editable.
- **The decision, not the dollar** — make-vs-buy + the quantity crossover are the hero output; cost is always a *banded* confidence interval, **hatched while assumption-based, solid only when validated**, never a fabricated figure.
- **Role-aware** — one analysis object, five lenses (design eng / cost eng / sourcing / mfg eng / economic buyer); the glass box is never hidden, only how-much-open-by-default is per-role.
- **2026 for this buyer** — clarity, tabular-mono numbers, one steel-blue accent, light+dark, no flash (flash reduces trust for aero/AV buyers).

## 2. Artifacts (all real, in the repo, building green)
- **Research:** `audience.md` (5 segments + 8-row opposing-needs matrix), `design-landscape.md` (20 adopt/avoid calls, sourced).
- **IA + flows:** `ia-and-flows.md` (role-gated glass-box over one analysis object; the upload→routing→glass-box-cost→calibrate→decision flow; tweak-rerun; designer→purchaser handoff).
- **Design system:** `design-system.md` + `frontend/src/components/glass-box/` (provenance, confidence, driver-breakdown, assumptions, calibration, process-comparison, decision, readout, role-lens) + light/dark tokens in `globals.css`. Showcase route **`/design-system`** renders it against real engine output.
- **Marketing site:** **`/`** (black-box-vs-glass-box hero on the *same* real $14.14/unit) + **`/method`** (show-our-work). Honesty held: no decimal-exact, no fabricated accuracy.
- **Platform:** the role-gated 5-lens **`/cost`** + **`/analyze`** workspace, bound to real `report_to_dict`.
- **Critique + validation:** `design-critique.md`, `design-validation-protocol.md` (validate with Zoox + one user per segment).

## 3. Live now
- `http://localhost:3000` — marketing · `/method` · `/cost` (role lenses, glass box) · `/design-system` · dark-mode toggle. Fresh backend on `:8000` emits routing + confidence.

## 4. Honest gaps → BUILD HARNESS (designed-for + flagged on-screen)
- **Per-shop calibration is not over the API yet.** The engine/CLI bind a shop's real rates (`--shop`), but `POST /validate/cost` has no shop param — so the live CalibrationBar honestly reads *"Not calibrated — generic defaults."* Wiring the shop param + a multi-shop A/B is the next build step; the UI is already designed for it.
- Confidence/routing now flow (post-restart); a shareable/role-scoped analysis object + engine-as-MCP-server are flagged as workflow-integration follow-ups.

## 5. Handoff
**Validate with real users BEFORE further build** (`design-validation-protocol.md`): the Zoox Head of
Manufacturing (use `zoox-calibration-protocol.md`) + one user per segment — can they reach a decision, do
they trust the numbers, does each role find its view? Then implementation (API shop param, calibration
A/B, MCP) flows to the build harness.

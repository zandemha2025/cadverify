# Platform-Experience Designer — log

**2026-06-29 — STATUS: DONE (not blocked).**

Wired the existing glass-box component library into the LIVE part-as-object workspace as the role-gated, one-object, five-lens experience from `ia-and-flows.md`. Prior state: glass-box components existed but were only rendered in the `/design-system` showcase; the live `/cost` + `/analyze` workspace still ran the old Analyze/Cost/Tolerances/Share tabs with zero glass-box, role-lens, routing, confidence, or calibration.

## Built
- `components/workspace/PartWorkspace.tsx` — rebuilt: topbar Role Lens + Calibration bar; role→landing-tab; tabs Decision · Glass Box · Routing & DFM · Compare · Share; persistent 3D rail; role-scoped Share/Handoff.
- `components/cost/CostDecisionView.tsx` — elevated: DecisionHeadline + NumberReadout(confidence band) + RedesignBanner + drill-to-glass-box + Buyer Why-trust panel.
- `components/workspace/GlassBoxView.tsx` (new) — drivers + Σ check + confidence + editable assumptions (override → USER).
- `components/workspace/RoutingDfmView.tsx` (new) — RoutingCard + DfmMatrix (geometry-linked) + AnalysisDashboard.
- `components/workspace/CompareView.tsx` (new) — process board off real estimates + crossover.
- `lib/cost-views.ts` (new) — pure derivations (pickEstimate, buildCompareRows, parseCalibration…).
- `app/(app)/cost|analyze/page.tsx`, `app/page.tsx` — pass `defaultRole` (design / mfg).

## Verified
- `npx tsc --noEmit` exit 0; `npm run build` exit 0 (Compiled successfully; /cost, /analyze, /design-system prerendered).
- Live `POST /api/v1/validate/cost/demo` → 200 real drivers/decision/feasibility; CLI emits routing+confidence+crossover.

## Build gaps designed-for + flagged on-screen (owned by build harness)
- Live API (stale server process) omits `routing` + estimate `confidence` though the engine source emits both → views show build-gap notes, light up when served.
- No `shop` param on the API → Calibration bar honestly reads "Not calibrated"; multi-shop A/B Compare flagged.
- Override server re-cost, persisted scenarios, role-scoped shared object → wired as designed-for with honest gap toasts.

Did NOT restart the user's :8000 backend (shared infra; API surfacing is the build harness's domain). No backend code changed. No screenshots fabricated (no browser-driving tool in this environment); the green production build + the `/design-system` static render are the render proof.

Deliverable: `outputs/design/platform.md`.

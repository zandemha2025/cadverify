# RESUME-CLOUD — run this project from GitHub

**For a Claude Code session running in the cloud against this repo.** Local-machine state (worktrees, local venv, local Postgres, orchestrator memory) does not exist here — this file is self-contained. Read it fully before doing anything.

## What this project is
CadVerify — "Databricks for manufacturability & cost": a governed decision layer for manufacturing engineers. A deterministic engine produces DFM findings and glass-box should-cost decisions where every number carries provenance (MEASURED / SHOP / USER / DEFAULT) and nothing is `validated` until real shop quotes are measured. The build discipline that produced this codebase: feature branch off `dev` → tests green → WIP behind a feature flag → adversarial verification → gated merge. `prod` stays demo-ready at all times.

## Current state (2026-07-03)
- `dev` = W3 merged (batch-cost job type, migration `0012_batch_cost`, org-scoped `GET /api/v1/catalog/portfolio` savings roll-up; triple adversarial PASS — isolation / honesty / correctness, high confidence; batch-costed numbers proven byte-identical to `POST /validate/cost`).
- `prod` = one gate behind `dev`; promotion pending an explicit founder OK.
- Test baseline: **797 passed / 24 env-only failures / 15 skipped** (see below for why the 24 are expected).

## Environment setup (cloud)
- **Backend** (Python 3.12, per `backend/Dockerfile`):
  `cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt`
  Run tests from `backend/`: `.venv/bin/python -m pytest -q`
- **Expected failures on a clean clone: exactly 24** — `test_costing_gates` (16) + `test_costing_accuracy` (8). They need an STL parts corpus via `CADVERIFY_PARTS_DIR`, which is not in the repo. ENV-ONLY, **not regressions** — never chase them, and never "fix" them by weakening the tests. Everything else must be green.
- Live-Postgres tests (`test_cross_tenant_isolation`, `test_catalog_api`, `test_portfolio_api`, `test_migration_*`) skip without `DATABASE_URL`. To run them: Postgres 16, a **throwaway** database, `alembic upgrade head`, then follow each file's docstring. CI reference: `.github/workflows/ci.yml`.
- `backend/data/shop_profiles/` is committed (gitignore exception) so cost-API tests pass from a clean clone.
- **Frontend**: `cd frontend && npm install`; gates are `npx tsc --noEmit`, `npm test`, `npx next build`. This is a **NONSTANDARD Next.js** app — read `frontend/AGENTS.md` and `frontend/node_modules/next/dist/docs/` before touching routing or data-fetching.

## Non-negotiable rules
1. **NO STUB MASQUERADING AS REAL.** No fabricated numbers, no silent egress, `/health` never lies. Honest empty/withheld states instead of fake values.
2. **Never self-certify correctness of cost/DFM magnitudes.** New numeric behavior ships as `Provenance.DEFAULT` with the literal `[assumption, not shop-validated]` caveat and `validated=False`. Only real measured ground truth (the Zoox flywheel) flips anything.
3. **Branch discipline in the cloud: never push to `dev` or `prod`.** Work on `feat/*` (code) or `design/*` (design) branches and push those; the founder's local orchestration loop gates every merge with adversarial verifiers. Product-design work: read `DESIGN-MISSION.md` at the repo root first — it is binding.
4. Frontend `package.json` gotcha: every frontend branch conflicts on the `"test"` script line; resolve by UNION of the `--test` file lists, then validate the JSON parses.

## Next work (priority order)
1. `dev → prod` promotion (founder decision, then packet regen must come from the merged prod).
2. **E-now freeze checkpoint**: regenerate the Zoox validation packet from merged prod (`outputs/long-horizon-plan.md` §5; basis: `outputs/verify/*.md`, `outputs/validation-packet.md`, `outputs/truth-engine-validation.md`) → the G3 Zoox session becomes schedulable. Agenda add: ask Zoox how they'd want part-in-context to work (validates plan §W3.5 rung 2 vs 3).
3. **W4 governed libraries**: DB-backed, versioned, effective-dated rate/material/shop assets + CRUD + engine cache invalidation. W3.5 rung 1 (declared context fields: `program / parent_assembly / units_per_parent / annual_volume`, USER provenance) can ride this — it unlocks honest $/year portfolio math.
4. E-now wave 2 (tolerance input surface; Zoox-gated coefficients).

## Map of the repo's own documentation
- Backlog source of truth: `outputs/audit/platform-gap-map.md` (+ sub-audits in `outputs/audit/`).
- Long-horizon plan: `outputs/long-horizon-plan.md` (tracks, gates G0–G4, walls W1–W5, §W3.5 part-in-context).
- Loop state (local orchestrator's handoff): `outputs/RESUME-AUTONOMOUS.md`. Deep 2026-07-02 context: `outputs/RESUME-HERE.md`.
- Verification verdicts: `outputs/verify/*.md`. Impl notes + specs: `outputs/impl/*.md`.
- Design: `DESIGN-MISSION.md` (root — the complete design mission) + `outputs/design/`.

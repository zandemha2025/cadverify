# RESUME — Autonomous Orchestration Loop (live)

**Updated 2026-07-03 by Fable (orchestrator).** Directive: full autonomous — Fable orchestrates, subagents build, Fable gates every merge. Continue the loop.

## Current state
- `dev == 74c5d38` (W3 merged). **`prod == 1b8a174` — PROMOTION PENDING**: the permission layer blocked `git push . dev:prod` (reads as prod deploy); founder to approve or add a Bash allow-rule for `git push . dev:prod`. Everything else about the W3 gate is complete.
- Backend suite post-merge: **797 passed, 24 failed (ENV-ONLY: test_costing_accuracy×8 + test_costing_gates×16, unset `CADVERIFY_PARTS_DIR`), 15 skipped.** W3 touched neither `src/costing` nor `src/analysis`.
- **GitHub remote is live**: `github.com/zandemha2025/cadverify`. main/dev/prod + all 27 merged feature branches + `feat/w3-portfolio-cost` pushed. **Policy: push `origin dev` (and `prod` once promotions are unblocked) after every gated merge** — founder works in the cloud too; pull before assuming local == remote, and if founder pushed to dev from the cloud, rebase the loop's work instead of colliding.

## W3 — LANDED on dev (merge 74c5d38, triple adversarial PASS, high conf)
Migration `0012_batch_cost` (batches.job_type; batch_items quantities/region/material_class/shop/cost_decision_id) · batch-cost job type (`BATCH_COST_ENABLED` default ON) · worker cost path with org-calibration binding — **parity crux: byte-identical to `/validate/cost`** (independent verifier script) · dedup-safe persist · cost results CSV · org-scoped `GET /api/v1/catalog/portfolio` with engine-grounded savings ranking (basis `decision.if_redesigned[q]`, JSONB string-key tolerant, withheld/validated honesty carried, no fabricated portfolio total). Isolation verifier ran its own two-org mesh-hash cross-contamination probe: clean.
Non-blocking notes (disclosed, not defects): batch cost path persists unconditionally (FK needs it) while the route gates on `COST_PERSIST_ENABLED`; savings baseline reads `decision.recommendation[q]` (tier-1 make-as-is) — honest, labeled with basis+qty. Builder impl note: `outputs/impl/w3-portfolio-cost-note.md`; spec: `outputs/impl/w3-portfolio-cost-spec.md`.

## IN FLIGHT
- Nothing building. W3 worktree at `<scratchpad>/wt/w3` can be pruned (`git worktree remove`) once prod is promoted.

## NEXT UP
1. **Promote dev→prod** (founder approval pending) → push `origin prod`.
2. **E-now freeze checkpoint** → regenerate the Zoox validation packet FROM MERGED PROD (long-horizon-plan §5; packet basis `outputs/verify/*.md` + `outputs/validation-packet.md` + `outputs/truth-engine-validation.md`) → G3 Zoox session becomes founder-schedulable. **Zoox agenda add (2026-07-03): ask how they'd want part-in-context to work against their real program structure** (validates W3.5 rung 2 vs 3).
3. **W4 governed libraries** (rate/material/shop assets, versioned + effective-dated). W3.5 rung 1 (declared context fields: program/parent/units_per_parent/annual_volume, USER provenance) can ride W4 — it unlocks honest $/year portfolio math.

## Design track (founder-driven, in the cloud)
Founder is running Claude Design on the web against the repo. **`DESIGN-MISSION.md` (repo root)** is the complete mission: register + three rejected directions + six signature moments + full screen/card/interaction inventory. Cloud sessions work on `design/*` branches ONLY (never dev/prod, never backend/). Founder judges concept frames first. New product idea captured 2026-07-03: **W3.5 part-in-context** (plan §W3.5 + gap-map addendum + design brief "context moment" — 3 honesty rungs, never AI-guessed).

## Forward queue
- E-now wave 2 (tolerance input surface — L; Zoox-gated coefficients).
- W1 Catalog UI / portfolio-door FE binding — **waits for the design world** (G0b; founder's cloud design round may land it).
- Non-blocking: pre-existing `/history` fabricated-type bug; `/{id}/pdf` WeasyPrint local libs.

## Gating protocol (unchanged)
Feature branch off dev → builder (opus, worktree under `<scratchpad>/wt/`, symlink backend/data) → 3 adversarial verifiers (isolation/honesty/correctness lenses) → read all verdicts → any FAIL routes back with the exact defect → merge --no-ff → full suite (accept ONLY the 24 env fails) → promote prod → push origin. Builders never merge/push. Every numeric cost change: DEFAULT/USER provenance + `[assumption, not shop-validated]` + validated=False. Never merge on a fabrication.

## RECURRING GOTCHA — frontend package.json
Every frontend branch conflicts on the `"test"` script line; resolve by UNION of `--test` file lists, then `python3 -c "import json;json.load(open('frontend/package.json'))"` before committing.

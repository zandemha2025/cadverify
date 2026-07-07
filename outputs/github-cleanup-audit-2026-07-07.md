# GitHub Cleanup Audit - 2026-07-07

Source of truth: live `gh` checks against `zandemha2025/cadverify`, plus local workflow inspection.

## Current GitHub State

- Active workflows: `CI / Deploy`, `STEP ingestion spike (B4)`, `Dependabot Updates`.
- Latest `STEP ingestion spike (B4)` run is green: run `28726761818`, 2026-07-05, branch `feat/step-spike`.
- Latest `CI / Deploy` run is red: run `28675945660`, 2026-07-03, branch `main`.
- Last `main` CI failure root causes in logs:
  - `libGLU.so.1` missing on the Ubuntu runner when importing `gmsh`.
  - Route-auth gate flagged `POST /validate/cost/demo`; the local route-auth gate has since been repaired in the enterprise build.
- Open PRs: 14, all Dependabot PRs against `main`, all stale/red/unstable.
- Branch protection: none on `main`, none on `dev`.
- Repository setting: `delete_branch_on_merge` is false.
- `git remote prune origin --dry-run` found no stale local tracking refs.

## Safe Cleanup Applied Locally

- `.github/workflows/ci.yml`
  - Added `workflow_dispatch` so CI can be rerun manually after the champion branch is pushed.
  - Added workflow concurrency so superseded runs on the same ref are canceled instead of piling up.
  - Installed native `gmsh` runtime libraries in backend CI and browser E2E before Python imports CAD code.
- `backend/src/parsers/step_mesher.py`
  - Treats missing native shared libraries (`OSError`) like missing `gmsh`, so capability detection degrades cleanly instead of crashing app import/test collection.
- `.github/dependabot.yml`
  - Reduced future PR flood.
  - Groups minor/patch backend, frontend, and GitHub Actions dependency updates.

## Cleanup That Needs Explicit Admin/Destructive Approval

- Close or refresh stale Dependabot PRs `#1` through `#14`.
  - They are all old branches from 2026-04-16 with red checks against an obsolete base.
  - Preferred path after the champion branch is green: close them with a note and let grouped Dependabot reopen clean PRs.
- Delete old failed Actions runs only if you want a cleaner UI.
  - This removes historical evidence; it does not make the product more correct.
  - Recommendation: keep failed product-debug runs, optionally delete only failed Dependabot noise.
- Enable branch protection after the next green `dev` or `main` run.
  - Require `CI / Deploy`.
  - Require PR review or explicit admin bypass.
  - Require branch up to date before merge.
- Enable `delete_branch_on_merge`.
- Prune remote feature branches after confirming what was merged into `dev` or `main`.
  - There are many live remote feature branches from 2026-07-01 through 2026-07-04.
  - No local stale tracking refs were found, so this is a remote governance cleanup, not a local git repair.

## Recommended Next Gate

1. Commit and push the current enterprise/champion build to `dev` or a `codex/...` PR branch.
2. Manually dispatch `CI / Deploy` on that ref.
3. Only after a green run, close stale Dependabot PRs and enable branch protections.

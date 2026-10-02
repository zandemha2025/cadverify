# CadVerify launch allowance and approved website

Candidate: `codex/free-checks-entry-flow`, based on production commit `5b94d76`.

- Integrated the user-approved website from `codex/buyer-first-site` in the separate `b9f4` worktree. Its uncommitted work and port 3101 preview were preserved. Kept the newer production authentication, signed proxy headers, session handling and nonce CSP.
- Kept the existing durable pilot intake, abuse checks, idempotent retries and confirmation receipt inside the approved new form design. Updated browser fixtures for CadVerify login/public copy.
- Public recorded sample; own CAD requires login/signup. Ten lifetime single-part checks, followed by Request paid access. Manual approval reuses the existing pilot entitlement; no Stripe or subscription billing was added.
- Closed anonymous legacy compute URLs and protected advanced compute. Durable per-account reservations stop concurrent overspend; failed work refunds, and saved records remain readable after exhaustion.
- The Verify and older DFM/cost workspaces share one ID across the preview, analysis and estimate of a submitted part. Deliberate rechecks start a new ID. Preview remounts reuse the completed blob without another computation.

## Evidence

- Full backend suite: **2,832 passed, 3 documented optional skips**.
- Frontend unit suite: **528 passed**; production build, TypeScript and changed-file lint passed.
- Route authentication coverage: **192 routes passed**.
- Backend type baseline: **209 errors vs the established 228-error ceiling**, passed; existing type debt remains.
- E2E fixture boundary and release-evidence unit checks: **14 passed**.
- Real local API/Next/PostgreSQL canary: signup, invalid-file refund, preview/DFM/cost as one credit, ten completed checks, eleventh rejected, legacy demo denied after exhaustion, saved report/PDF access and login persistence. See `local-canary.json`.
- Browser: approved desktop and mobile homepage; sample design/cost/source controls; own-part CTA leads to login; signup preserves destination and explains the ten-check allowance. Existing exhausted test account logged in and showed **0 of 10**, then rejected another guided check.
- **57 layout checks** across 19 public routes at 320px, 390px and 1440px, after fonts loaded: one main heading, valid section links, no horizontal overflow. See `site-layout-checks.json`.

- Restored production-backup rehearsal: migration 0048 → 0049 backfilled exactly 58 lifetime checks while preserving all 887 existing rows across 37 tables. See `production-backup-migration.json`.
- Real browser upload in the older cost workspace: STEP preview, DFM and cost completed under one ledger credit; the UI showed 9 remaining. See `legacy-workspace-canary.json`.
- The contact form saved exactly one durable local receipt; no email delivery was configured.
- Hosted browser checks found and prompted fixes for authentication labels including hint text and mobile code-block overflow. The final label was verified in the browser; the responsive checks above cover the layout fix.
- Hosted run `36964157509` passed the public, human, Design Studio, enterprise, role/failure, assembly, connector, 34-model CAD and restore journeys. Its load smoke correctly received 401 because it still called the legacy demo anonymously. Both load scripts now reuse the existing authenticated local fixture helper; the corrected smoke passed 6/6 requests (P95 3,787 ms), and the profile passed 12/12 at concurrency 2. Concurrency 4 encountered the existing per-organization limit of 3, as expected; no production protection was changed.
- Manual paid-access canary: approval enabled unlimited checks and the advanced route; returning the account to trial preserved its previous usage (1 used, 9 remaining). See `manual-access-canary.json`.

No production deployment has occurred for this candidate. Hosted CI and deployment approval are separate from this local verification.

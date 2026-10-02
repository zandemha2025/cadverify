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
- **38 layout checks** across 19 public routes at 390px and 1440px: one main heading, valid section links, no horizontal overflow. See `site-layout-checks.json`.

No production deployment has occurred for this candidate. Hosted CI and deployment approval are separate from this local verification.

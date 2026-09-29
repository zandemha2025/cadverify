# Production audit — 2026-09-29

## Outcome and deployment boundary

The working current application is **https://cadverify-web.onrender.com**. Disposable signup, logout, password login, uppercase `.STP` upload, costing and saved-record retrieval succeeded there. The Render API reports healthy PostgreSQL, Redis and worker, and build `ec6f8e1127fd8dc6b210b0d30d4919d141317609`, matching the main branch at audit start.

The originally requested **Fly deployment remains broken**: its API reports PostgreSQL unavailable and its login/signup endpoints return HTTP 500. The provider-level database cause and recovery need authenticated Fly access. **Vercel is disabled** (HTTP 402). Existing Fly accounts and saved data have not been verified on Render. Future AWS deployment plans are not evidence of a live AWS deployment.

**No audit fix has been deployed.** Changes are on `codex/production-audit-20260929`, based on current main. The initial July checkout was 444 commits behind main. Do not promote that old checkout or assume the July Fly release is equivalent to Render.

## Confirmed findings and status

Each issue was recorded before its fix. “Local” means verified in this checkout and isolated test services, not released to customers.

| ID | Severity / workflow | Reproduction and actual behavior | Root cause and expected correction | Status |
| --- | --- | --- | --- | --- |
| PROD-001 | Critical — Fly authentication/database | Fly `/health` repeatedly returns 503 with `postgres:false`; synthetic login and signup return 500 with empty web response bodies. | Database connectivity is failing. Exact provider/configuration cause is unconfirmed without authenticated logs; restore connectivity while preserving existing data. | **Blocked by provider access.** Render signup/login verified working independently; no account migration claimed. |
| PROD-002 | High — Fly homepage without WebGL | Browser without WebGL reaches the global error screen; retry repeats `Error creating WebGL context`. | Decorative 3D must fall back while the page remains usable. | **Already fixed on current main.** Local production homepage and CAD verification work without WebGL. July Fly still has the old behavior. |
| PROD-003 | High — obsolete public URL | Repository-listed Vercel URL and newest Vercel production deployment return 402 `DEPLOYMENT_DISABLED`. | Public entry links and provider routing need a single verified destination. | **Deployment guide corrected locally** to the working Render entry point. Repository homepage/provider redirects remain unchanged pending deployment ownership. |
| PROD-004 | High — release drift | Fly reports July manual release; Render reports September main SHA. Old checkout differs by 444 commits. | A release must identify the tested source and migration state. | **Identified.** Audit branch starts at Render's main SHA. Fly's exact image SHA remains unknown; AWS is only documented future intent. |
| PROD-005 | High — auth failure guidance | Inject/observe a 500 during login: UI reports invalid credentials; magic-link exchange similarly blames an expired link. | Unconditional credential/link fallback discarded service status. Shared auth recovery now distinguishes outage, throttling and actual input errors. | **Fixed locally**, `2924065`. Browser checks cover 500, 429, 401 and 422 with retry. |
| PROD-006 | Medium — public mobile layout | At 390px, Method/Teams content extends beyond its cards/viewport; hidden overflow conceals it. | Fixed desktop columns need responsive grid tracks. | **Fixed locally**, `076849b`. Card and text bounds checked at 320/390/820/1280px; Platform's existing fix also verified. |
| PROD-007 | Medium — magic-link hydration | In React Strict Mode, load a token fragment: first effect scrubs URL; replay loses token and shows missing-link state. | Preserve the captured token across effect replay while still clearing the URL. | **Fixed locally**, `48af610`. Browser reproducer fails before and passes after. This was a dev-mode finding, not a claimed production incident. |
| PROD-008 | High — cost explanations | Driver formulas omit applied markup/overhead; public Method example says 0.082 hr × $52/hr = $6.39. | Shared cost-model explanations and captured examples must disclose all multipliers and reconcile numerically. | **Fixed locally**, `bd16e70`. Actual costing unchanged; 108 costing tests pass. |
| PROD-009 | High — CAD rejection/retry | Empty or malformed STEP returns a specific API reason that UI discards; injected 503 wrongly tells users to re-export CAD. | Shared assembly probe must parse structured errors and separate file rejection from service/session failures. | **Fixed locally**, `5c1db46`. Real bad/empty/oversize/native-format refusal; 503 retry with retained file, 429 delay, and 401 sign-in recovery pass in browser. |
| PROD-010 | High — homepage entry links | Three homepage CTAs on local/Fly/AWS origins jump to Render, losing that origin's session. | Hard-coded deployment URLs should be same-origin `/verify`. | **Fixed locally**, `4ae52e2`. All CTAs preserve origin and signed-out login return path. |
| PROD-011 | Medium — desktop workspace navigation | At 1440px, long tab labels overflow their flex-shrunk buttons and overlap neighbors. | Keep button widths inside the existing horizontal scroller. | **Fixed locally**, `d6c3618`. Text bounds pass at 1280/1440/1600px; last tab and 390px selector remain usable. |
| PROD-012 | Medium — original CAD readback | Save `source.step` and `costable.stl`, then call unqualified `read_source_artifact`: sorted lookup returns derived STL. | Original-source lookup must select the existing `source` basename; derived mesh retrieval stays separate. | **Fixed locally**, `6b4715a`. Red/green regression and actual stored-upload byte hash pass. This is a helper-contract defect; no user-facing download corruption was established. |
| PROD-013 | Low — rate-limit heading | A validation 429 displays correct retry delay but generic “Verification could not finish” heading. | Failure classifier missed `Too many verification requests`, the wording generated by the shared recovery helper. | **Fixed locally**, `5382acd`. Actual shared-message regression passes; mobile 429 recovery now passes. Rate limits unchanged. |
| PROD-014 | Medium — assembly recovery | Real 18-part STP renders; inject analysis-only 503 and UI says analysis unavailable, with no retry action. | Reuse the existing analysis fetch and stale-run guard through a retry button. | **Fixed locally**, `744d24a`. Browser retries the real analysis, retains selected part, costs 18/18 parts, and makes no duplicate model/GLB or single-part cost requests. |

| PROD-015 | Medium — release dependency gate | CI rejects the unchanged lock by resolving newer versions into an empty temporary output. | Seed the temporary output from the lock, so existing compatible pins are validated and upgrades remain explicit. | **Fixed locally.** Lock reproduces byte-for-byte; Bandit reports zero medium/high findings and pip-audit finds no known vulnerabilities. |

## Working error states and intentional boundaries

- Health reports its failing PostgreSQL dependency honestly. The public status page explicitly says its monitoring feed is not live.
- Missing invite/magic tokens are handled on current source; empty pilot submission is rejected without sending a message.
- STEP/STP are already supported by the parser. A blanket “STP unsupported” diagnosis was not supported by testing. Authentication failure and misleading upload errors were distinct issues.
- Native SolidWorks formats require an exchange export; refusal is explicit and does not create a record or make a success claim.
- Invalid input, oversize input and geometry refusals must not be treated as service outages. Conversely, service/rate-limit errors must not blame the file.
- Single-part costing intentionally waits for successful validation. A rejected validation produces no cost request; this is a safety boundary, not missing work.
- Assembly analysis is currently in-process and does not create the same saved decision as the single-part route. The UI does not claim a saved record. Durable assembly sessions are a capability gap to decide separately, not silently fabricated storage coverage.

## Verification evidence

### Verified on the live Render deployment

A disposable test account completed signup → workspace → sign out → password login. A native file chooser uploaded `audit-cube.STP`, producing a watertight 20×15×10mm model, 2.72cm³ volume, should-cost at six quantities, and a saved record that reopened successfully (`01M3Q5M93VFP3S0C2FCCJ8HR6Q`). Screenshot: `render-stp-record.png`. The account was signed out afterward. The user's own account and old Fly data were not accessed or transferred.

Fly's public demo also accepted a real `.stp` with correct geometry; its authenticated database-dependent flows remain unavailable. No destructive production test, real charge, customer message, or infrastructure mutation was performed.

### Verified locally with real services and CAD

- **484 frontend tests pass**, no failures/skips; TypeScript, changed-source ESLint and Next production build pass.
- Backend baseline: **2,224 passed**, 79 skipped; its sole Redis failure passes against the correct isolated Redis port. **76 initially skipped PostgreSQL integration tests then pass** against a separate migrated disposable database. Two optional OCP XDE cases and the full external corpus were not run in that baseline.
- **47 focused STEP/invalid-upload/units/IGES checks**, **108 costing checks**, and **18 source-artifact checks** pass. One PostgreSQL case skipped by the source-only invocation was already exercised in the separate PostgreSQL run.
- Existing human E2E on the production build: **PASS, health 100, zero issues**. Enterprise E2E on a fresh local organization: **PASS, health 100, 9/9 golden journeys**, including machines/rates, actuals/calibration, keys, environment-aware verification, persisted history and exact-quantity portfolio results. These do not imply external identity-provider validation.
- STEP matrix: `.step`/`application/step`, `.stp`/`application/octet-stream`, `.STEP`/`model/step`, `.STP`/empty MIME all pass real classification, validation, costing and stored retrieval. Browser covers chooser and drag/drop. Block-with-hole geometry matches analytic volume `(3000 − 90π) mm³`; all saved line items reconcile within API rounding tolerance.
- Empty, malformed, unsupported and 101MiB files reject at all three API endpoints with 400/400/400/413. Browser additionally verifies same-file retry after 503, 429 delay, session-expiry action, and no-WebGL operation.
- **Six realistic STEP cases pass**: AP203 geometry, AP203 PMI, AP242 editions 1/2/3, and a periodic-surface regression. Each reaches a saved numeric result, supports disposition, and reopens after refresh. Native SolidWorks assembly is truthfully refused. Zero unexpected HTTP errors, console errors or failed requests in the successful run. Report: `../../.gstack/qa-reports/representative-cad-browser-production-audit-cad4-20260929.json`.
- **AS1 assembly passes**: 18 real solids, 5 unique designs, 18/18 analyzed, 0 part errors, 32 geometric contact/interference pairs. An injected analysis outage recovers via retry without reuploading geometry. Contact pairs are signals, not manufacturing faults. Report: `../../.gstack/qa-reports/assembly-recovery/result.json`.
- Original saved STEP bytes read identically through `.step`, `.stp`, and unqualified source lookup: SHA-256 `76923244d66efcbf1eb1639a26a6b4b6bd20fd73eaf44ad1b95268dddf61103a`. Derived STL remains separate (`stored-source-readback.json`).

- **Mobile recovery: PASS, health 100, 20/20 scenarios, zero issues, 7/7 evidence contracts.** Covers 320px signup/navigation, generated CAD, duplicate-tap prevention, refresh during verification, tablet batches/dialogs, keyboard/responsive records, bad-file recovery, capacity retry, history/worker failures, seven HTTP error classes, network interruption, browser history, revoked-cookie rejection, browser restart and interrupted direct upload with exactly one reconciled batch. Report: `../../.gstack/qa-reports/mobile-recovery-production-audit-mobile9-20260929.json`.
- **Direct object storage: PASS, 4/4 browser checks.** A real multipart ZIP reaches separate local Moto transient/durable buckets and the worker; expired URL retry succeeds, another account cannot access the upload, and four failed PUT attempts terminate with abort and no batch creation. Zero unexpected console/network failures. Frontend/API build IDs both match product commit `35685298ed0797dd598c64db7e21323fa0dc192c` before and after the run. This is S3-compatible local emulation, not AWS infrastructure validation. Report: `../../.gstack/qa-reports/direct-s3-batch-production-audit-s3b-20260929.json`.

### Test-harness corrections

Existing browser scripts assumed an old onboarding flow, modal pipeline, concurrent cost requests and obsolete error copy. They now dismiss onboarding through its actual Close button, observe the nonmodal status, await the saved decision before navigating, verify cost is skipped after validation failure, and allow fast results that intentionally suppress the progress indicator. No network failure was hidden to make a product test pass. Browser teardown now closes the browser once; redundant context-first teardown hung after Chrome had exited. All 31 relevant harness unit checks pass.

Earlier failed runs are retained as diagnostic evidence, not counted as passing release gates. These include a dirty enterprise fixture account, dev-mode navigation cancellation, old UI assertions, an unconfigured local S3 CSP origin, and the original missing assembly retry action. The configured run passes with the exact local origin allowed by the existing CSP mechanism; no security policy was weakened.

## Remaining work / limits

- The audit's exercised scenarios are complete. External provider access, deployment approval and the untested boundaries below remain.
- Public pages visited: homepage, company, Method, Platform, Teams and its five roles, Security, Developers, Status, Docs, API reference, pilot, privacy, terms, DPA and auth/missing-token pages. This does not claim every external link, provider integration or every state has been exercised.
- A generated Gmsh IGES shell was unsuitable as a solid browser fixture; it is excluded honestly. Existing focused IGES tests pass, but a representative customer IGES browser import remains unverified.
- Real CAD browser checks compare displayed figures with the engine and saved record. Independent analytic ground truth was checked for the cube-with-hole fixture; no independent engineering certification of every sample is claimed.
- No full corpus sweep, real external SSO/SCIM provider session, paid integration, mail delivery, destructive admin action, production load test, real AWS infrastructure/KMS validation or cross-deployment account migration was performed.
- Restoring Fly requires authenticated provider logs. Confirm whether the user needs an existing Fly account/data recovered or can use Render. Deployment, redirects and account migration remain subject to explicit approval.

## Release handoff

All ten actionable source defects have local fixes. Product code was built and exercised at `35685298ed0797dd598c64db7e21323fa0dc192c`; later changes only close redundant browser teardown, align the evidence wording and record this report. No schema migration or production deployment is included. The generated local `frontend/AGENTS.md` change is excluded from the patch, as are runtime credentials, raw logs and CAD artifacts.

Before production release: review the draft PR and approve a deployment target; confirm provider access; preserve existing account/data boundaries. Fly restoration additionally needs its actual database error from authenticated provider logs. Local verification is not a claim that the Fly service has been repaired.

Commit hooks were initially unconfigured in the worktree. Every audit commit was replayed through the real repository hooks; all attestations now pass the CI policy locally. This only changes commit metadata. The tested pre-attestation commit `35685298ed0797dd598c64db7e21323fa0dc192c` has an identical tree to `ded5866`; the original build IDs in retained evidence are intentionally preserved.

### PROD-015 — dependency lock check attempts an implicit upgrade (Medium)

CI's lock check recompiles to a nonexistent temporary output, so pip-compile selects newly released versions for the input's open ranges. The unchanged committed lock is then rejected (21 package upgrades, including server/CAD dependencies), before Bandit or the vulnerability audit runs. Expected: validate that the current locked graph still satisfies the input, with dependency upgrades handled explicitly and the existing vulnerability gate retained. Fix: seed the temporary output with the committed lock before compiling, allowing pip-tools to reuse its existing pins. CI logs: `ci-security.log`; dependency versions are not changed by this fix.

PROD-015 verification: the seeded lock recompiles byte-for-byte using the same pinned pip 24.0 and pip-tools 7.5.3 as CI. This follows [pip-tools documented output-file behavior](https://pip-tools.readthedocs.io/en/stable/#understanding-output-file-behavior). Bandit completes with 0 medium/high findings (47 low findings remain); pip-audit reports no known vulnerabilities. Dependency versions and runtime code are unchanged.

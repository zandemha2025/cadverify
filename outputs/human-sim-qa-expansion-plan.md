# Human-Sim QA Expansion Plan

Scope: P7 from the Real Finish Line spec.

## Current Coverage

Tracked runners:
- `scripts/e2e/human-e2e-runner.mjs`
- `scripts/e2e/enterprise-domain-runner.mjs`
- `scripts/e2e/p7-role-failure-journey-runner.mjs`

CI gate:
- `.github/workflows/ci.yml` job `browser-e2e`
- Runs the full local app with Postgres, Redis, Chrome, backend, frontend, and worker.
- Uploads JSON, Markdown, screenshots, and app logs.

Current human journey coverage:
- Public marketing routes and visible non-final-copy sweep.
- Login gate, weak-password rejection, real signup, onboarding.
- Authenticated Verify shell and rail surfaces.
- Command palette jump, notification panel, authenticated app routes.
- Mobile smoke for public home and Verify shell.
- Real STEP upload through the Verify UI.

Current enterprise-domain journey coverage:
- Org admin signup and membership assertion.
- Unauthenticated org-data rejection.
- Governed rate-card publish and default/non-validated assertions.
- Machine floor declaration with rates and envelopes.
- Ground-truth ingest below validation floor with recalibration refusal.
- Calibration UI proof of governed defaults and real-data floor.
- Developer key creation and one-time secret reveal.
- Sour-service/high-pressure/high-temperature STEP verification.
- Portfolio exposure withheld until volume, then server-side annualized math.
- Programs UI and cost history verification.

Current role/failure coverage:
- Unauthenticated redirects for cost, batch, history, developer settings, and Verify when mounted.
- Unauthenticated same-origin API proxy rejection.
- Invalid credentials and injected login network failure.
- Authenticated unsupported batch upload.
- Injected cost-history API failure rendering.
- Optional seeded low-role admin-denial and Verify calibration-gate checks.
- Visible-copy sweep for unfinished/product-internal language.

## Missing Human-Sim Branches

### Role Journeys

- Viewer: can read records/catalog where allowed, cannot mutate machines/rates/ground truth.
- Analyst/member: can verify parts and create decisions, cannot publish governed libraries.
- Org admin: can manage members, publish governance changes, inspect audit logs.
- Superadmin/platform admin: can cross-org administer only where explicitly privileged.

### Failure Journeys

- Invalid CAD magic bytes.
- Unsupported native CAD extension.
- Huge CAD / triangle-count cap.
- Geometry invalid but repair guidance visible.
- Cost timeout path.
- Worker down while async/batch/reconstruct routes are used.
- API rate limit path with user-visible retry guidance.
- Expired/revoked invite acceptance.
- Stale rate-card or stale decision after library publish.
- Redis/database degraded health behavior.

### Domain Scenarios

- Oil and gas: sour/high-pressure environment, NACE material routing.
- Aerospace: AS9100/NADCAP/FAI/certification expectations.
- Automotive: PPAP-style inspection and high-volume cost sensitivity.
- Medical: biocompatibility/traceability/regulated material constraints.

### Cross-Checks

- Browser-visible numbers must match API responses for unit cost, annualized exposure, machine rates, material class, validation state, and provenance.
- Every “validated” visible chip must trace to API `validated === true`; seeded journeys should assert no validated claim appears.
- Every rejected/unsupported CAD journey must produce structured backend detail and a visible user-facing explanation.

### Artifacts

- Screenshots already exist.
- Add optional video/trace capture for failure/debug runs.
- Add rubric JSON for the drop-audit moment:
  - cinematic
  - data_true
  - environment_correct
  - drillable
  - conversational

## Recommended Build Slices

### P7.A - Shared E2E Harness Utilities

Owns:
- `scripts/e2e/lib/*`
- Refactor common browser setup, artifact writing, screenshots, API helpers, issue scoring.

Guardrails:
- Existing `test:e2e:full` output shape remains compatible.

### P7.B - Role Matrix Runner

Owns:
- `scripts/e2e/role-matrix-runner.mjs`
- `frontend/package.json`
- `.github/workflows/ci.yml`

Status:
- Initial role/failure runner landed as `scripts/e2e/p7-role-failure-journey-runner.mjs` and is wired into `test:e2e:full`.
- Low-role coverage currently depends on optional `E2E_VIEWER_*` hooks.

Guardrails:
- Mutations as viewer/member must fail.
- Admin-only actions must succeed as admin.
- Cross-org data must not leak.

### P7.C - Failure Journey Runner

Owns:
- `scripts/e2e/failure-journey-runner.mjs`
- Any small backend fixtures under `backend/tests/assets/`

Status:
- Initial failure coverage landed inside `p7-role-failure-journey-runner.mjs`.
- Remaining expansion should add invalid CAD magic, huge CAD, geometry repair, worker-down, rate-limit, expired invite, and stale-decision branches.

Guardrails:
- Unsupported/invalid/huge files never silently collapse.
- Failure states are visible, structured, and non-final-copy clean.

### P7.D - Domain Scenario Runner

Owns:
- `scripts/e2e/domain-scenario-runner.mjs`

Guardrails:
- O&G, aerospace, automotive, and medical scenarios assert actual API/business outputs, not just route rendering.

### P7.E - Drop-Audit Rubric

Owns:
- `scripts/e2e/lib/rubric.mjs`
- Runner Markdown/JSON outputs.

Guardrails:
- Rubric scores are evidence-bearing.
- A seeded journey can score readiness, but cannot imply validated accuracy.

## QA/QC Gate

Any medium-or-higher issue in a browser runner exits non-zero. CI publishes artifacts even on failure.

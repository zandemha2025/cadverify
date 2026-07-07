# CadVerify Enterprise Build Log

Authoritative scope: `/Users/nazeem/.codex/attachments/ab923bca-2366-410e-913f-738b657be45d/pasted-text.txt`

Mission: build the enterprise-worthiness apparatus across the seven Real Finish Line domains. The machine can make proof possible, but it must not manufacture proof. Real validated accuracy, live SSO exercise, pen test, SOC 2, real-scale customer load, real cloud restore, and customer corpus ingestion remain real-system gates until exercised with those systems.

## Operating Rules

- Proof first. UI polish never substitutes for measured correctness.
- `validated=true` is never earned from synthetic, seed, fixture, demo, or default data.
- Unknown CAD formats, unsupported geometry, missing credentials, and external systems route to honest triage or handoff, never silent collapse.
- Coordinator owns the DAG, file ownership, merge order, and gates.
- Builders work in disjoint slices; verifiers audit before the next build wave compounds on top.
- All human, credential, customer-data, auditor, and live-infra dependencies go to `outputs/handoff-queue.md`.

## QA/QC Levels

| Level | Owner | Gate |
| --- | --- | --- |
| L0 Builder self-check | Builder agent or coordinator | Local syntax/type/unit checks for changed files |
| L1 Domain verifier | Independent verifier | Goal-backward audit against the phase success criteria |
| L2 Guardrail verifier | Coordinator plus tests | No synthetic validation, no fake enterprise-exercised claim, honest triage |
| L3 Human-sim E2E | Browser runner | Role/failure/domain journeys with screenshots/artifacts |
| L4 Security/tenant audit | Security verifier | Tenant isolation, RBAC, session/key safety, audit coverage |
| L5 Ops/CI audit | SRE verifier | CI, deploy, backup/restore, migration rollback, observability, load harness |
| L6 Champion packet protocol | Coordinator | Evidence template plus real-system handoff items |

## Cycle Log

### 2026-07-07 - Cycle 0: Control Plane

- Read authoritative finish-line spec.
- Read GSD autonomous workflow and recovered actual workflow path under `/Users/nazeem/.claude/get-shit-done/`.
- Determined existing `.planning/ROADMAP.md` is stale relative to the current product and this finish-line spec; do not blindly execute the old April roadmap.
- Started domain mapping agents:
  - P1 validated-accuracy apparatus: `019f3aba-80a8-7693-8198-b0ff9e4e7f61`
  - P2 CAD breadth: `019f3aba-9a33-7110-a189-1ee4d238d339`
  - P3 enterprise IT acceptance: `019f3aba-b5a0-7133-9bc1-bab086c6b3c0`
  - P4 production operations: `019f3aba-cfac-72f2-922b-5119c1ed2bf2`
  - P5 enterprise workflow completeness: `019f3aba-f1ba-7f92-9595-42e893438254`
  - P6 real integrations: `019f3abb-0ec1-7441-94ee-90aa9d4afe54`
- Agent pool reached concurrency cap before P7; coordinator owns P7 human-sim QA/QC mapping locally.

### 2026-07-07 - Cycle 1: Domain Map and P1 First Slice

Domain map findings:
- P1: Ground truth is real but mutable and too thin for enterprise proof. Missing actual-hours/evidence metadata, residual dashboard, approved validation runs, and pilot-report generator.
- P2: Backend supports STL/STEP/IGES, but frontend and batch are stale for IGES. Unsupported native/drawing files need explicit triage items, not silent omission.
- P3: SAML exists but SCIM, group-role mapping, verified-domain provisioning, and server-side session revocation are missing.
- P4: CI does not trigger `dev`; frontend Docker/Helm are unproven; DR/restore/load/queue-health apparatus is incomplete.
- P5: Onboarding is static; Programs are labels; cost decisions lack signoff/staleness; notifications are derived, not durable; cert/spec workflows are absent.
- P6: CSV bridges exist; no SAP/PLM connector apparatus, formal API compatibility policy, RFQ model, or named customer feed harness.
- P7: Current browser E2E is strong for happy-path human/enterprise journeys but lacks role matrix, failure journeys, domain scenario breadth, video/trace artifacts, and rubric scoring.

Implemented P1 first slice:
- Added nullable validation actuals metadata to `ground_truth_records` via migration `0026_gt_actuals_metadata`.
- Added source/evidence/hour fields to ORM/API/service/dataclass public path.
- Extended CSV import to parse `source_type`, hours, invoice date, evidence SHA-256, evidence URI, and vendor quote id.
- Enforced `source_type=synthetic|seed|demo|stand_in` as `stand_in=True`, so synthetic rows can exercise the apparatus but cannot count toward validation.
- Added parser and migration tests.

Verification:
- `backend/.venv/bin/python -m pytest backend/tests/test_groundtruth_import.py backend/tests/test_costing_groundtruth.py backend/tests/test_w5_plumbing.py backend/tests/test_migration_0026.py -q`
- Result: 45 passed, 5 skipped.
- `.venv/bin/python -m alembic heads` from `backend/`
- Result: `0026_gt_actuals_metadata (head)`.
- Python compile check for touched backend modules passed.

Known verification note:
- Running all `backend/tests/test_migration_*.py` together exposed an existing `test_migration_0009` SQLAlchemy metadata re-import collision. Targeted migration tests and Alembic head discovery pass.

### 2026-07-07 - Cycle 2: P2 CAD Breadth Honesty

Implemented P2 first slice:
- Added IGES/IGS parity to batch ZIP extraction so batch accepts the same core CAD formats as the single-file validate route.
- Added explicit native-CAD/drawing taxonomy for common formats (`.sldprt`, `.sldasm`, `.prt`, `.catpart`, `.dwg`, `.dxf`, etc.).
- Changed ZIP extraction behavior so CAD-adjacent native/drawing files become visible `skipped` batch items with a reason instead of being silently omitted.
- Counted initially skipped/failed extracted items in `failed_items` at batch creation so progress math is terminal and honest.
- Updated frontend CAD accept contract to include STL, STEP/STP, and IGES/IGS from one shared source.
- Updated upload-facing product/docs copy to match the actual parser contract.

Verification:
- `backend/.venv/bin/python -m pytest backend/tests/test_batch_service.py backend/tests/test_batch_router.py -q`
- Result: 37 passed.
- `cd frontend && npm test -- src/lib/cad-file.test.ts`
- Result: 216 passed.
- `backend/.venv/bin/python -m py_compile backend/src/services/batch_service.py backend/src/api/batch_router.py backend/src/api/routes.py`
- Result: passed.
- `node --check scripts/e2e/human-e2e-runner.mjs && node --check scripts/e2e/enterprise-domain-runner.mjs`
- Result: passed.

Guardrail:
- IGES support here is tessellated geometry support, not B-rep/PMI semantics. Native CAD/drawing conversion remains a handoff item until a licensed converter or customer export workflow exists.

### 2026-07-07 - Cycle 3: P4 Ops Proof Slice

Sidecar worker:
- P4 operations worker `019f3ac6-3672-7b00-81a2-41aa43f805c4`.

Implemented P4 first slice:
- CI now triggers on `dev` pushes and PRs targeting `dev`, not only `main`.
- CI container proof job now depends on both backend and frontend, validates local and enterprise Compose configs, builds a frontend production image as proof, and builds/pushes the backend image only on `main` pushes.
- Local and enterprise Compose configs now include backend and frontend healthchecks.
- Frontend Dockerfile now matches the current non-standalone Next runtime path using pruned production deps plus `next start`.
- Added static ops proof test for CI triggers, Compose healthcheck surface, frontend Docker runtime mode, and Fly deploy config.

Verification:
- `backend/.venv/bin/python -m pytest --noconftest backend/tests/test_enterprise_ops_proof.py -q`
- Result: 4 passed.
- `backend/.venv/bin/python -m py_compile backend/tests/test_enterprise_ops_proof.py`
- Result: passed.

Known verification note:
- Docker is not installed in this local environment (`docker: command not found`), so no local Docker build is claimed. The CI workflow now carries that image/Compose proof.

### 2026-07-07 - Cycle 4: P7 Role/Failure Human-Sim QA Slice

Sidecar worker:
- P7 role/failure worker `019f3ac6-2167-7380-8c3a-9914f891e443`.

Implemented P7 first slice:
- Added `scripts/e2e/p7-role-failure-journey-runner.mjs`.
- Runner covers unauthenticated protected-route redirects, unauthenticated API rejection, invalid login, injected login network failure, authenticated unsupported batch upload, injected cost-history API failure rendering, optional seeded low-role checks, and visible non-final-copy sweeps.
- Runner writes JSON/Markdown artifacts and screenshots under `.gstack/qa-reports`.
- If the app is unavailable in standalone use, it writes an explicit `SKIPPED_UNAVAILABLE` report instead of pretending the app passed.
- Wired `frontend/package.json` so `npm run test:e2e:full` now runs human, enterprise-domain, and P7 role/failure journeys.

Verification:
- `node --check scripts/e2e/p7-role-failure-journey-runner.mjs`
- Result: passed.
- `APP_URL=http://127.0.0.1:9 E2E_ARTIFACT_DIR=<tmp> npm run test:e2e:p7 --prefix frontend`
- Result: exited 0 with explicit `SKIPPED_UNAVAILABLE` JSON/Markdown reports.
- Combined targeted gate:
  - `backend/.venv/bin/python -m pytest backend/tests/test_groundtruth_import.py backend/tests/test_costing_groundtruth.py backend/tests/test_w5_plumbing.py backend/tests/test_migration_0026.py backend/tests/test_batch_service.py backend/tests/test_batch_router.py backend/tests/test_enterprise_ops_proof.py -q`
  - Result: 86 passed, 5 skipped.
  - `cd frontend && npm test -- src/lib/cad-file.test.ts`
  - Result: 216 passed.
  - `node --check scripts/e2e/human-e2e-runner.mjs && node --check scripts/e2e/enterprise-domain-runner.mjs && node --check scripts/e2e/p7-role-failure-journey-runner.mjs`
  - Result: passed.
  - `git diff --check`
  - Result: passed.
  - `cd backend && .venv/bin/python -m alembic heads`
  - Result: `0026_gt_actuals_metadata (head)`.

### 2026-07-07 - Cycle 5: P5 Decision Governance Slice

Implemented P5 first slice:
- Added cost-decision governance metadata: `approval_status`, `approved_by_user_id`, `approved_at`, `approval_note`, `stale_at`, and `stale_reason`.
- Added Alembic migration `0027_cost_decision_governance`; current head is now `0027_cost_decision_governance`.
- Added owner-scoped approve/reopen API routes for saved cost decisions. Approval changes metadata only; the saved glass-box `result_json` artifact remains immutable.
- Added stale-decision marking when governed rate, shop, or material library versions are published.
- Added frontend API contract, history-table Governance status, and detail-page governance panel with approve, reopen, stale warnings, and approval notes.
- Added regression tests for migration shape, list/detail governance fields, approve/reopen behavior, and stale-update dispatch.
- Fixed the ORM ownership relationship ambiguity introduced by the new approver FK by explicitly mapping `CostDecision.user` through `user_id`.
- Cleaned test DB session mocks so synchronous `session.add()` no longer emits false AsyncMock warnings.

Verification:
- `backend/.venv/bin/python -m pytest backend/tests/test_cost_persist_api.py backend/tests/test_migration_0027.py -q`
- Result: 27 passed.
- Combined targeted enterprise gate:
  - `backend/.venv/bin/python -m pytest backend/tests/test_groundtruth_import.py backend/tests/test_costing_groundtruth.py backend/tests/test_w5_plumbing.py backend/tests/test_migration_0026.py backend/tests/test_batch_service.py backend/tests/test_batch_router.py backend/tests/test_enterprise_ops_proof.py backend/tests/test_cost_persist_api.py backend/tests/test_migration_0027.py -q`
  - Result: 113 passed, 5 skipped, 1 local LibreSSL warning.
  - `cd frontend && npm test -- src/lib/cad-file.test.ts`
  - Result: 216 passed.
  - `cd frontend && npm run lint -- src/lib/api.ts 'src/app/(app)/cost-decisions/[id]/page.tsx' src/components/CostDecisionHistoryTable.tsx`
  - Result: passed.
  - `cd frontend && npm run build`
  - Result: passed.
  - `node --check scripts/e2e/human-e2e-runner.mjs && node --check scripts/e2e/enterprise-domain-runner.mjs && node --check scripts/e2e/p7-role-failure-journey-runner.mjs`
  - Result: passed.
  - `git diff --check`
  - Result: passed.
  - `cd backend && .venv/bin/python -m alembic heads`
  - Result: `0027_cost_decision_governance (head)`.

Known verification note:
- The skipped backend checks require local Postgres or real sample-part corpora. They remain honest skips, not passes.

### 2026-07-07 - Cycle 6: P3 Server-Side Session Revocation Slice

Implemented P3 first slice:
- Added `users.session_version` via migration `0028_user_session_version`; current Alembic head is now `0028_user_session_version`.
- Extended dashboard session cookies to carry `session_version` while still accepting pre-0028 two-field cookies as version `0`.
- Added DB-backed validation for dashboard cookies and `/api/v1` session-cookie fallback: deactivated users and stale session versions are rejected server-side.
- Added `POST /auth/logout-all` for self-service revocation of all dashboard sessions.
- Added `POST /api/v1/admin/users/{id}/revoke-sessions` for superadmin account-wide session invalidation.
- Account deactivation/reactivation now bumps `session_version` when the active state changes, so pre-offboarding cookies cannot be reused after reactivation.
- Updated password, Google OAuth, magic-link, and SAML issuers to mint cookies with the current user session version.
- Added tests for signed payload versioning, legacy cookie compatibility, revoked-session rejection, logout-all behavior, SSO issuer mocks, and migration shape.

Verification:
- `backend/.venv/bin/python -m pytest backend/tests/test_auth_dashboard_session.py backend/tests/test_auth_password.py backend/tests/test_sso_key_minting.py backend/tests/test_saml.py backend/tests/test_migration_0028.py -q`
- Result: 47 passed, 1 skipped, 1 local LibreSSL warning.
- Combined targeted enterprise gate:
  - `backend/.venv/bin/python -m pytest backend/tests/test_groundtruth_import.py backend/tests/test_costing_groundtruth.py backend/tests/test_w5_plumbing.py backend/tests/test_migration_0026.py backend/tests/test_batch_service.py backend/tests/test_batch_router.py backend/tests/test_enterprise_ops_proof.py backend/tests/test_cost_persist_api.py backend/tests/test_migration_0027.py backend/tests/test_auth_dashboard_session.py backend/tests/test_auth_password.py backend/tests/test_sso_key_minting.py backend/tests/test_saml.py backend/tests/test_migration_0028.py -q`
  - Result: 160 passed, 6 skipped, 1 local LibreSSL warning.
  - `cd frontend && npm test -- src/lib/cad-file.test.ts`
  - Result: 216 passed.
  - `cd frontend && npm run build`
  - Result: passed.
  - `node --check scripts/e2e/human-e2e-runner.mjs && node --check scripts/e2e/enterprise-domain-runner.mjs && node --check scripts/e2e/p7-role-failure-journey-runner.mjs && git diff --check`
  - Result: passed.
  - `APP_URL=http://127.0.0.1:9 E2E_ARTIFACT_DIR=/tmp/cadverify-p7-e2e-check-main E2E_RUN_ID=unavailable-main node scripts/e2e/p7-role-failure-journey-runner.mjs`
  - Result: explicit `SKIPPED_UNAVAILABLE` report.
  - `cd backend && .venv/bin/python -m alembic heads`
  - Result: `0028_user_session_version (head)`.

Known verification note:
- The full password auth DB flow remains skipped locally without `DATABASE_URL=postgresql://...`, so logout-all has unit-level and route-code proof here, not live-Postgres proof.

### 2026-07-07 - Cycle 7: P7 Governance Human-Sim Extension

Sidecar worker:
- P7 governance worker `019f3ad9-65ac-7971-8f79-863d18d03814`.

Implemented P7 governance extension:
- Extended `scripts/e2e/p7-role-failure-journey-runner.mjs`.
- When a live authenticated app is available, it creates a saved cost decision via `/api/proxy/validate/cost`, opens the real detail page, approves with a note, verifies backend governance fields, reopens the decision, publishes a governed rate-card version, and verifies the stale warning on the detail page.
- If app/backend/auth/data are unavailable, it records explicit skips instead of claiming a pass.

Verification:
- `node --check scripts/e2e/p7-role-failure-journey-runner.mjs`
- Result: passed.
- `APP_URL=http://127.0.0.1:9 E2E_ARTIFACT_DIR=/tmp/cadverify-p7-e2e-check-main E2E_RUN_ID=unavailable-main node scripts/e2e/p7-role-failure-journey-runner.mjs`
- Result: explicit `SKIPPED_UNAVAILABLE` report.

Queued next slices from sidecar audits:
- P5 durable notifications: implement durable inbox as migration `0029_notifications_inbox` (not `0028`, because session revocation now owns `0028`), with first-class notification rows, per-user reads, governance/cost/ground-truth/webhook producers, API, and frontend swap from derived notifications.
- P6 integration apparatus: implement static offline connector registry plus `integration_runs` ledger for SAP/PLM/ground-truth CSV dry-runs, delegating to existing manifest/ground-truth parsers and not storing raw CSV by default.

### 2026-07-07 - Cycle 8: P5 Durable Notification Inbox + Real-Part Test Recovery

Implemented P5 durable inbox first slice:
- Added `notifications` and `notification_reads` tables via Alembic migration `0029_notifications_inbox`; current Alembic head is now `0029_notifications_inbox`.
- Added durable notification ORM models, idempotent emit/reopen, source-resolution, list, mark-one-read, mark-all-read, and serialization service.
- Added `/api/v1/notifications` API for unread/open inbox reads plus per-user read markers.
- Added producers for saved cost decisions and governance change requests; governance approvals/rejections resolve the matching review notification.
- Swapped the Verify bell and `/notifications` page from derived/static rows to durable backend rows and optimistic read actions.
- Added service, API, and migration tests for the inbox route shape and idempotent semantics.
- Fixed cost-decision governance serialization so mocked or legacy non-datetime rows do not crash metrics/detail routes.
- Restored the real automotive CAD validation suites by resolving `ecu_automotive_batch2.zip` into ignored `.pytest_cache/parts/...`; the suites now run against real STL geometry instead of skipping due an empty stale scratchpad path.
- Fixed the dev/test DB engine so SQLite URLs no longer receive Postgres pool arguments. Full schema creation remains Postgres-only because the models use Postgres `JSONB`.
- Restored API-key role fallback compatibility for older test doubles by calling `lookup_user_role` only when the joined role is absent.

Verification:
- `cd backend && .venv/bin/python -m pytest tests/test_notifications_api.py tests/test_notification_service.py tests/test_migration_0029.py -q`
- Result: 9 passed.
- `cd backend && .venv/bin/python -m pytest tests/test_costing_accuracy.py tests/test_costing_gates.py tests/test_costing_groundtruth.py -q`
- Result: 48 passed against real automotive STL fixtures from `ecu_automotive_batch2.zip`.
- `cd backend && .venv/bin/python -m pytest -q`
- Result: 1310 passed, 54 skipped, 161 warnings.
- `cd frontend && npm test`
- Result: 216 passed.
- `cd frontend && npm run build`
- Result: passed.
- `cd backend && .venv/bin/python -m alembic heads`
- Result: `0029_notifications_inbox (head)`.
- `git diff --check`
- Result: passed.
- `cd frontend && npm run test:e2e:p7`
- Result: explicit `SKIPPED_UNAVAILABLE` report at `.gstack/qa-reports/qa-report-p7-role-failure-2026-07-07.md`.

Known verification note:
- Live browser E2E could not be run locally because Docker/Postgres are unavailable (`docker: command not found`) and SQLite is not schema-compatible with the Postgres `JSONB` models. The P7 runner recorded the unavailability honestly; the full live-stack browser gate remains a CI/Postgres responsibility.

### 2026-07-07 - Cycle 9: P6 Offline Integration Apparatus

Implemented P6 first slice:
- Added `integration_runs` ledger via Alembic migration `0030_integration_runs`; current Alembic head is now `0030_integration_runs`.
- Added static offline connector registry for `sap_manifest_csv`, `plm_manifest_csv`, and `ground_truth_csv`.
- Added integration service that hashes uploaded CSV bytes, records source system/kind, row totals, valid/invalid counts, errors, status, mode, and import counts without storing raw CSV.
- Added dry-run mode that delegates to the existing manifest and ground-truth CSV parsers without importing rows.
- Added import mode that delegates to existing manifest/ground-truth importers and honors the global write kill switch.
- Added `/api/v1/integrations/connectors`, `/api/v1/integrations/runs`, and `/api/v1/integrations/runs/{id}`.
- Added `/integrations` operator page with connector cards, dry-run/import control, and recent run history.
- Added shell and command-palette navigation to the integrations surface.
- Added human-sim route coverage so `/integrations` is part of the app route sweep.
- Added service, API, and migration tests for connector registry, dry-run behavior, import delegation, no-raw-payload posture, route shape, and migration chain.

Verification:
- `cd backend && .venv/bin/python -m pytest tests/test_integration_service.py tests/test_integrations_api.py tests/test_migration_0030.py tests/test_manifest_ingest.py tests/test_groundtruth_import.py -q`
- Result: 29 passed, 4 skipped.
- `cd backend && .venv/bin/python ../scripts/ci/check_route_auth.py`
- Result: `route-auth-coverage OK (127 routes across api modules)`.
- `cd backend && .venv/bin/python -m pytest -q`
- Result: 1318 passed, 54 skipped, 161 warnings.
- `cd frontend && npm test`
- Result: 216 passed.
- `cd frontend && npm run build`
- Result: passed; `/integrations` is present as a dynamic app route.
- `cd backend && .venv/bin/python -m alembic heads`
- Result: `0030_integration_runs (head)`.
- `node --check scripts/e2e/human-e2e-runner.mjs`
- Result: passed.
- `git diff --check`
- Result: passed.
- `cd frontend && npm run test:e2e:p7`
- Result: explicit `SKIPPED_UNAVAILABLE` report at `.gstack/qa-reports/qa-report-p7-role-failure-2026-07-07.md`.

Known verification note:
- This is offline integration apparatus, not a claim of live SAP/PLM connectivity. Live connector completion remains pending customer/system credentials or exported customer feed samples.

### 2026-07-07 - Cycle 10: Truth Audit Hardening

Implemented honesty hardening after a coordinator stub/placeholder audit:
- Added `outputs/truth-audit-2026-07-07.md` to separate built/proven, apparatus-only, disabled/handoff, and honest terminal states.
- Made S3/remote manifest batch input reject unconditionally with `501 S3_INPUT_UNSUPPORTED` until an object-fetch adapter exists; no env flag can accidentally create doomed S3 batches.
- Removed the unused frontend `createBatchS3` helper so the frontend API layer no longer exposes a disabled capability as a callable helper.
- Changed the integrations UI headline/copy to "Offline CSV connector runs" and to display that live credentials are not used.
- Tightened SAM-3D availability so it remains false unless the renderer can emit real face-ID buffers, the SAM backend is importable, and model weights exist. The current face-ID renderer gap is still explicit.

Verification:
- `cd backend && .venv/bin/python -m pytest tests/test_sam3d.py tests/test_batch_router.py tests/test_batch_hardening.py -q`
- Result: 53 passed.
- `cd frontend && npm test`
- Result: 216 passed.
- `cd frontend && npm run build`
- Result: passed.
- `git diff --check`
- Result: passed.

### 2026-07-07 - Cycle 11: P4 Queue Health Operator Surface

Implemented P4 queue-health slice:
- Added `src/services/ops_health_service.py` with PII-safe summaries for jobs, batches, batch items, webhook retries, Redis reachability, and arq worker heartbeat.
- Added admin-only `GET /api/v1/admin/ops/queue-health`, org-scoped for org admins and global for superadmins.
- Added `scripts/ops/check-queue-health.py` so operators can fetch the queue-health proof endpoint from a deployment.
- Added low-cardinality Prometheus queue gauges plus orphan-sweep counter.
- Added optional `WORKER_STRICT_HEALTH=1` readiness behavior so missing arq worker heartbeat can gate `/health` when desired.
- Added tests for batch heartbeat classification, async-tier probe truthfulness, admin route scoping, and static PII-safe ops surface proof.

Verification:
- `cd backend && .venv/bin/python -m pytest tests/test_metrics.py tests/test_health.py tests/test_ops_health_service.py tests/test_admin_ops_health.py tests/test_batch_tasks.py tests/test_enterprise_ops_proof.py -q`
- Result: 41 passed, 1 warning.
- `cd backend && .venv/bin/python -m py_compile src/api/metrics_registry.py src/api/metrics.py src/api/health.py src/jobs/batch_tasks.py src/services/ops_health_service.py tests/test_metrics.py tests/test_health.py`
- Result: passed.
- `cd backend && .venv/bin/python ../scripts/ci/check_route_auth.py`
- Result: `route-auth-coverage OK (128 routes across api modules)`.

### 2026-07-07 - Cycle 12: P3 SAML JIT Group Mapping

Implemented P3 SAML group-mapping slice:
- Added `saml_group_mappings` via Alembic migration `0031_saml_group_mappings`; current migration head is now `0031_saml_group_mappings`.
- Added `src/services/org_saml_service.py` to normalize SAML attributes, match exact attribute/value pairs, choose the strongest same-org mapped role, reject multi-org ambiguity fail-closed, and apply JIT membership without demoting or deprovisioning existing memberships.
- Added org-admin CRUD at `/api/v1/orgs/saml/group-mappings`, using the existing org-admin dependency and mutation kill switch.
- Wired SAML ACS to apply group attributes before issuing the dashboard session cookie; ambiguous mappings return `403 saml_group_mapping_ambiguous` and do not set a session.
- SAML JIT assignment sets the mapped org active on login so org-scoped reads follow the IdP assertion.
- Fixed SAML and magic-link account provenance so new rows pass `auth_provider="saml"` / `auth_provider="magic_link"` instead of inheriting the Google default.
- Updated the current-state map and truth audit: SAML group mapping is built/proven locally, while live IdP certification, SCIM, verified-domain provisioning, SOC 2, pen test, and real customer IdP exercises remain enterprise handoff work.

Verification:
- `cd backend && .venv/bin/python -m py_compile src/db/models.py src/services/org_saml_service.py src/auth/models.py src/auth/saml.py src/auth/oauth.py src/auth/magic_link.py src/api/org_routes.py tests/test_org_saml_service.py tests/test_saml.py tests/test_sso_key_minting.py tests/test_migration_0031.py`
- Result: passed.
- `cd backend && .venv/bin/python -m pytest tests/test_org_saml_service.py tests/test_saml.py tests/test_sso_key_minting.py tests/test_migration_0031.py -q`
- Result: 26 passed, 1 warning.
- `cd backend && .venv/bin/python ../scripts/ci/check_route_auth.py`
- Result: `route-auth-coverage OK (131 routes across api modules)`.
- `cd backend && .venv/bin/python -m alembic heads`
- Result: `0031_saml_group_mappings (head)`.
- `git diff --check`
- Result: passed.
- `cd backend && .venv/bin/python -m pytest -q`
- Result: 1339 passed, 54 skipped, 161 warnings.

### 2026-07-07 - Cycle 13: P5/P6 RFQ Supplier Evidence Packages

Implemented RFQ/sourcing workflow slice:
- Added `rfq_packages` via Alembic migration `0032_rfq_packages`; current migration head is now `0032_rfq_packages`.
- Added `src/services/rfq_package_service.py` to create durable org-scoped supplier evidence packages from saved cost decisions.
- Package snapshots include cost-decision JSON, estimates CSV, generated PDF where available, supplier brief, manifest exact normalized-stem match, declared part context, and warning flags.
- Raw CAD is not implied: package rows and ZIP manifests record `raw_cad_included=false` unless a same-org completed batch ZIP blob linked to the cost decision still exists.
- Live procurement is not implied: package rows and ZIP manifests record `live_supplier_send=false`; no supplier registry/send/network behavior was added.
- Added `GET/POST /api/v1/rfq-packages`, `GET /api/v1/rfq-packages/{id}`, and `GET /api/v1/rfq-packages/{id}/download.zip`.
- Added `/rfq-packages` app ledger, `/rfq-packages/[id]` detail, sidebar/command-palette navigation, and cost-decision quick `RFQ ZIP` export.
- Added `/rfq-packages` to the human app route sweep.
- Updated the current-state map and truth audit so RFQ packages are built/proven locally while supplier registry, supplier qualification, and live RFQ send remain future enterprise work.

Verification:
- `cd backend && .venv/bin/python -m py_compile src/services/rfq_package_service.py src/api/rfq_packages.py src/db/models.py tests/test_rfq_package_service.py tests/test_rfq_packages_api.py tests/test_migration_0032.py`
- Result: passed.
- `cd backend && .venv/bin/python -m pytest tests/test_rfq_package_service.py tests/test_rfq_packages_api.py tests/test_migration_0032.py -q`
- Result: 7 passed.
- `cd backend && .venv/bin/python ../scripts/ci/check_route_auth.py`
- Result: `route-auth-coverage OK (135 routes across api modules)`.
- `cd backend && .venv/bin/python -m alembic heads`
- Result: `0032_rfq_packages (head)`.
- `cd frontend && npm test`
- Result: 216 passed.
- `cd frontend && npm run build`
- Result: passed; `/rfq-packages` and `/rfq-packages/[id]` are present as dynamic app routes.
- `node --check scripts/e2e/human-e2e-runner.mjs`
- Result: passed.
- `git diff --check`
- Result: passed.
- `cd backend && .venv/bin/python -m pytest -q`
- Result: 1346 passed, 54 skipped, 161 warnings.

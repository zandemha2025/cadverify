# CadVerify Truth Audit - 2026-07-07

Purpose: answer the fear directly. A feature is only "true" when the code path is present, tested, and not quietly substituting fixture/demo behavior for the real thing. Everything else is named as apparatus, disabled, or handoff-required.

## Truth Labels

- **Built/proven locally**: implementation exists and has local unit/integration/build proof.
- **Apparatus only**: code and tests make real proof possible, but no live customer/system exercise has happened.
- **Disabled/handoff**: route or surface exists, but the capability is intentionally unavailable until a dependency is real.
- **Honest terminal state**: a user-facing status such as `partial`, `skipped`, `validated=false`, or empty history that is a valid result, not unfinished product work.

## Built/Proven Locally

- Offline CSV integration apparatus: connector registry, `/api/v1/integrations` routes, `integration_runs` ledger, dry-run/import delegation, `/integrations` UI, tests, and build proof.
- Durable notification inbox: backend rows, per-user reads, API, Verify bell, notifications page, and first producers.
- Cost-decision governance: approve/reopen/stale metadata, API, saved-decision UI, exports unaffected.
- RFQ/supplier evidence packages: durable `rfq_packages` ledger, org-scoped create/list/detail/download APIs, package ZIP contents, stale/unapproved/unvalidated warning flags, manifest/context enrichment, route/auth tests, frontend `/rfq-packages` ledger/detail, and cost-decision quick package export.
- Server-side dashboard session revocation: `session_version`, logout-all, admin revoke, issuer updates.
- SAML JIT group mapping: `0031_saml_group_mappings`, org-admin CRUD, ACS attribute application, strongest-role same-org matching, active-org selection, ambiguous multi-org fail-closed handling, and provider provenance tests are implemented and locally verified.
- Batch ZIP upload: ZIP path, manifest import, unsupported native-CAD triage, cost/DFM worker paths, S3 rejection tests.
- Real automotive STL fixture suite now runs against `ecu_automotive_batch2.zip` via ignored cache instead of silently skipping an empty corpus.

## Apparatus Only, Not Live-Certified

- SAP/PLM/ERP integrations are **offline CSV export connectors**, not live SAP/PLM adapters. The UI now says "Offline CSV connector runs" and displays `live creds: no`.
- RFQ packages are **local evidence bundles**, not live supplier sends. They explicitly record `live_supplier_send=false`, and raw CAD is absent unless already recoverable from same-org batch ZIP blob storage.
- SAML group mapping is built locally but not live-certified against a customer's Okta, Azure AD, or ADFS tenant.
- Human-sim E2E apparatus exists and is wired, but this local machine cannot run the full live stack because Docker/Postgres are unavailable. Standalone runs record `SKIPPED_UNAVAILABLE`; CI/live-stack runs are the real gate.
- P1 validation apparatus can ingest and separate real vs synthetic actuals, but real validated accuracy still requires customer actuals and signed-off validation runs.
- CI/container/health proof exists, but backup/restore, migration rollback, load/soak, and cloud restore drills still require executable run/proof.

## Disabled/Handoff, Not A Product Claim

- **Remote S3/manifest batch input** is not implemented. It now rejects unconditionally with `501 S3_INPUT_UNSUPPORTED` before creating any batch row; the stale frontend S3 helper was removed.
- **SAM-3D semantic segmentation** is scaffolded but not operational as a SAM-3D claim. Availability now stays false unless the renderer can emit real face-ID buffers, the SAM backend is importable, and model weights exist. The current renderer still has the face-ID gap.
- **Image-to-mesh reconstruction** is deployment-configured. Without local TripoSR or explicit remote-egress opt-in, it returns `501 RECONSTRUCTION_UNAVAILABLE`; it is not silently available.
- **AP242/GD&T/PMI extraction** is conditional on OCP XDE modules. STEP/IGES production paths are tessellated mesh paths, not B-rep/PMI semantic readers.
- **Live SAP/ERP/PLM API adapters, supplier registry/qualification/live RFQ send, SCIM, live IdP certification, verified-domain provisioning, SOC 2, pen test, live cloud restore, and real-scale load** remain handoff/enterprise work.
- **Company pilot form** has no lead-capture backend. It prevents default submit and does not fake a success message.

## Honest Terminal States, Not "Half-Built"

- `partial` integration/import status means some rows were accepted and some were flagged. It is a valid enterprise ETL outcome when backed by row counts/errors.
- Unsupported CAD/native/drawing files are visible skipped or failed rows, not silent omissions.
- `validated=false`, default rate-card labels, withheld cost, empty webhook delivery logs, and empty notification history are honest data states when the platform lacks the evidence to claim more.

## Verification After This Audit

- `cd backend && .venv/bin/python -m pytest tests/test_sam3d.py tests/test_batch_router.py tests/test_batch_hardening.py -q` -> 53 passed.
- `cd backend && .venv/bin/python -m pytest tests/test_org_saml_service.py tests/test_saml.py tests/test_sso_key_minting.py tests/test_migration_0031.py -q` -> 26 passed, 1 warning.
- `cd backend && .venv/bin/python -m pytest tests/test_rfq_package_service.py tests/test_rfq_packages_api.py tests/test_migration_0032.py -q` -> 7 passed.
- `cd backend && .venv/bin/python -m pytest -q` -> 1346 passed, 54 skipped, 161 warnings.
- `cd backend && .venv/bin/python -m alembic heads` -> `0032_rfq_packages (head)`.
- `cd backend && .venv/bin/python ../scripts/ci/check_route_auth.py` -> `route-auth-coverage OK (135 routes across api modules)`.
- `cd frontend && npm test` -> 216 passed.
- `cd frontend && npm run build` -> passed.
- `node --check scripts/e2e/human-e2e-runner.mjs` -> passed.
- `git diff --check` -> passed.

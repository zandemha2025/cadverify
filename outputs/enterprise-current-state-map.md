# CadVerify Enterprise Current-State Map

Source: coordinator scan plus P1-P6 sub-agent audits on 2026-07-07.

Truth audit: `outputs/truth-audit-2026-07-07.md` is the current stub/placeholder ledger. Treat anything marked apparatus-only or disabled/handoff as not enterprise-complete until its live proof exists.

## P1 - Validated Accuracy Apparatus

Current:
- Ground-truth API/import/recalibration exists and is org-scoped.
- Confidence intervals fall back to assumption bands with `validated=false`.
- Synthetic stand-ins are excluded from real metrics.
- Calibration refuses below the real-record floor.
- The real automotive STL validation fixture archive is resolved into an ignored cache, so local accuracy/gate/ground-truth suites now execute on real geometry instead of silently collapsing to zero parts.

Remaining:
- Append-only validation ledger and approved validation-run records.
- Residual dashboard by process, material, geometry family, shop, and volume.
- Pilot-report generator/export.
- Stronger evidence-backed real-data approval path.

First slice done:
- Added source/evidence/hour metadata and synthetic source-type guard.

## P2 - CAD Breadth

Current:
- Backend single-file path supports STL, STEP/STP, IGES/IGS.
- Batch ZIP extraction supports STL, STEP/STP, and IGES/IGS.
- Common native CAD and drawing formats are triaged into visible skipped batch rows with reason text instead of silently disappearing.
- Frontend upload guards and upload-facing copy use the same STL/STEP/IGES contract.
- STEP/IGES are tessellated via gmsh/OCC, not B-rep/PMI semantics.
- Declared tolerance class and part context exist.
- Manifest can carry declared program/assembly context.
- Non-watertight cost path withholds cost through structured geometry invalid paths.
- SAM-3D remains disabled as an operational claim until a real face-ID rendering pass exists.

Remaining:
- Native CAD conversion strategy beyond explicit unsupported/triage states.
- Assembly/multi-body/weldment guardrails.
- PMI/GD&T “not read” status when OCP/XDE is absent.
- Drawing/PDF declared-spec workflow.

## P3 - Enterprise IT Acceptance

Current:
- SAML login/ACS/SLO/metadata exists.
- SAML JIT group-to-org-role mapping exists with org-admin CRUD, migration `0031_saml_group_mappings`, ACS attribute application, active-org selection, strongest-role same-org matching, and fail-closed multi-org ambiguity handling.
- Org invites, membership lifecycle, deactivation, tenant isolation, and audit export exist.
- Dashboard sessions now carry `session_version` and can be revoked server-side.
- Superadmins can revoke all sessions for an account; users can self-revoke all sessions with logout-all.
- Account deactivation/reactivation bumps `session_version`, so old dashboard cookies cannot be reused after offboarding.
- SAML and magic-link account creation now set honest `auth_provider` provenance instead of inheriting the Google default.

Remaining:
- SCIM 2.0.
- Live IdP certification against customer Okta/Azure/ADFS tenants.
- Verified-domain claim and org provisioning.
- Retention enforcement and tamper-evident audit posture.
- Security questionnaire, DPA, SOC 2, and pen-test evidence packet.

## P4 - Production Operations

Current:
- CI runs backend tests, frontend build, browser E2E, backend/frontend container proof, and deploy on `main`.
- CI triggers on `main` and `dev` pushes/PRs.
- Local and enterprise Compose files include backend/frontend healthchecks.
- Helm chart exists.
- JSON logs, Sentry scrubbing, health, metrics, and worker mechanics exist.
- Admin queue-health endpoint, CLI proof script, Prometheus queue gauges, and optional worker-strict health gate expose PII-free job, batch, webhook retry, Redis, and worker-heartbeat posture.

Remaining:
- Helm proof.
- Backup/restore and migration rollback drills as executable scripts.
- Worker-failure browser E2E scenarios in live-stack CI.
- Synthetic load/soak harness.
- Object-storage abstraction for multi-node deploys.
- Remote S3/manifest batch input is hard-disabled until an object-fetch adapter exists.
- SLO and incident runbook.

## P5 - Enterprise Workflow Completeness

Current:
- Machine inventory CRUD/import/catalog prefill exists.
- Manifest backend exists.
- Programs roll up via part context labels.
- Governed library workflow exists for rate/shop/material assets.
- Cost-decision PDF/CSV/JSON exports exist.
- Cost decisions now carry approval/signoff metadata and can be approved/reopened through the API and saved-decision detail page.
- Governed rate/shop/material publishes mark older org decisions stale without mutating the saved decision artifact.
- Cost-decision history shows governance status.
- Durable notification inbox exists with backend rows, per-user reads, list/read/read-all API, Verify bell integration, `/notifications` page integration, and first producers for cost decisions plus governance change requests.
- Deterministic frontend ask dock exists.
- RFQ/supplier evidence packages exist as durable org-scoped records with migration `0032_rfq_packages`, create/list/detail/download APIs, ZIP exports, manifest/context enrichment, warning flags for stale/unapproved/unvalidated decisions, explicit `raw_cad_included` and `live_supplier_send=false`, `/rfq-packages` UI, detail page, and cost-decision quick export.

Remaining:
- Guided first-run onboarding state.
- Manifest/BOM command center.
- Programs as first-class objects.
- Full verification record export.
- Additional notification producers for ground-truth thresholds, webhook/integration failures, and operator handoff states.
- Governed shop certifications and per-part/process specs.
- Backend persisted ask/what-if engine.

## P6 - Real Integrations

Current:
- CSV bridge for manifest and ground truth exists.
- Batch ZIP plus manifest exists.
- Webhook delivery hardening exists.
- `/api/v1` structure and OpenAPI/Scalar exist.
- Offline connector registry exists for SAP manifest CSV, PLM manifest CSV, and quote/actuals CSV.
- `integration_runs` ledger records org, user, connector, source system/kind, mode, status, file SHA-256, file size, row counts, errors, import counts, and `raw_stored=false`.
- `/api/v1/integrations` exposes connector registry, dry-run/import execution, list, and detail routes.
- `/integrations` app page exposes connector cards, dry-run/import controls, and recent run history.
- The integrations UI explicitly labels these as offline CSV connector runs and says live credentials are not used.
- Dry-run mode reuses existing manifest and ground-truth parsers without importing rows; import mode delegates to those importers and respects the global write kill switch.
- RFQ packages produce local supplier evidence ZIPs, not live RFQ sends.

Remaining:
- Live SAP/ERP API adapter with customer credentials.
- Live PLM connector with explicit disabled/not-configured behavior.
- Supplier registry, supplier qualification, and live RFQ send workflow.
- Formal API compatibility/versioning policy and snapshots.
- Named customer-feed dry-run harness and evidence packet.

## P7 - Human-Sim QA Expansion

Current:
- CI browser E2E starts the full app with Postgres, Redis, Chrome, backend, frontend, and worker.
- Human runner covers public routes, auth, app surfaces, mobile smoke, and STEP upload.
- Enterprise runner covers org admin signup, governed rates, machine floor, below-floor ground truth, developer key reveal, service-world STEP verification, portfolio math, and programs/history.
- P7 role/failure runner is wired into `npm run test:e2e:full`.
- P7 runner covers unauthenticated redirects/API denial, invalid login, injected login network failure, unsupported batch upload, injected cost-history API failure, optional seeded low-role gates, and visible unfinished-copy sweeps.
- P7 runner now includes a live-stack governance path for saved cost decision approve, reopen, governed rate publish, and stale-warning display when authenticated app/data are available.
- Human route sweep now includes `/rfq-packages` so the package ledger is part of the app-surface traversal.
- Local no-server runs produce explicit `SKIPPED_UNAVAILABLE` artifacts; this environment cannot run live-stack browser E2E because Docker/Postgres are not installed and SQLite cannot host the Postgres `JSONB` schema.

Remaining:
- Full generated role matrix with seeded viewer/member/admin accounts in CI.
- Broader failure journeys: invalid CAD magic bytes, huge CAD/triangle caps, geometry repair guidance, worker down, rate limit, expired invite.
- Browser/API cross-check assertions across more surfaces.
- O&G/aerospace/automotive/medical seeded scenarios.
- Video/trace capture for failures.
- Drop-audit rubric scoring.

# CadVerify Enterprise Live Integration and Production Proof Plan

Prepared: 2026-07-08

## Bottom Line

CadVerify is deployed and working as a web app, and the repo already contains strong simulated enterprise QA. It is not yet enterprise-certified in the way an Exxon-style buyer would mean it. The current proof is pre-human simulation plus production web proof, not live SSO/SCIM, SAP, PLM, procurement, security-audit, or production-scale certification.

The finish line is:

1. Real IdP sandbox proof: Okta and Microsoft Entra SAML/OIDC sign-in plus SCIM joiner/mover/leaver provisioning and deprovisioning.
2. Real system sandbox proof: SAP/ERP and PLM/BOM connectors running against vendor/customer sandbox tenants or approved exported fixtures.
3. Real procurement sandbox proof: RFQ/approval workflow can create draft procurement artifacts or cXML/supplier handoff evidence without pretending to send live supplier commitments.
4. Real CAD/proof corpus: public CAD files from NIST/ABC plus customer-like generated scenarios are used before any human pilot.
5. Security proof: OWASP ASVS/WSTG coverage, NIST-style testing methodology, external pen-test/SOC2 evidence binder.
6. Ops proof: strict worker health, object storage, load/soak tests, restore drills, observability, alerting, and rollback/canary proof.

## Current Repo Truth

These are strengths, not failures; they keep the truth boundary clean.

- SAML exists as a service-provider path under `/auth/saml`, but live Fly config currently runs password auth, not enterprise SSO.
- SAML group mapping is JIT assignment only. The code explicitly says it is not SCIM and missing groups never demote/deprovision.
- Integration connectors are offline CSV contracts only. `sap_manifest_csv`, `plm_manifest_csv`, and `ground_truth_csv` record hashes, counts, statuses, and errors, but do not use live SAP/PLM credentials.
- RFQ currently creates downloadable evidence packages. It explicitly says it is not live procurement and no supplier was contacted.
- Existing enterprise gauntlets cover SSO/SCIM pressure, SAP/ERP simulation, PLM/BOM simulation, RFQ package honesty, procurement approval, security review pressure, answer fidelity, screenshot sanity, and load/restore smoke. They also explicitly state they are not certification by Exxon, SAP, PLM vendors, suppliers, or auditors.
- Live `/health` checks Postgres and Redis; worker liveness is only a hard gate when `WORKER_STRICT_HEALTH=1`. The last live proof had worker state `unknown`.

## Research Anchors

- SAML: OASIS SAML 2.0 defines the framework for exchanging security information between online business partners and is the enterprise SSO baseline. Microsoft Entra documents SAML as a widely used enterprise option, and recommends nonproduction testing for SSO setup.
- SCIM: RFC 7644 defines SCIM as the HTTP protocol for provisioning and managing identity data across domains, with Users and Groups resources. Okta's SCIM guide expects building, connecting, and testing a SCIM API service.
- SAP: SAP Integration Suite is positioned for application/process integration, API governance, B2B integration, hybrid integration, and centralized monitoring/security. SAP S/4HANA exposes business APIs through SAP Business Accelerator Hub / OData services.
- PLM: PTC Windchill REST Services expose Product Management entities such as Part, BOM, PartUse, and UsageOccurrence; BOM reading examples use OData endpoints. Autodesk Platform Services exposes data-management APIs for CAD/cloud file access.
- Procurement: cXML is the business-document protocol between procurement apps, e-commerce hubs, and suppliers. Coupa exposes supplier APIs and supports cXML fields/methods for purchase-order routing.
- Security: OWASP ASVS provides a basis for testing web-app technical security controls; OWASP WSTG provides a penetration-testing guide. NIST SP 800-115 gives a methodology for planning, conducting, analyzing, and mitigating technical security tests. AICPA Trust Services Criteria cover Security, Availability, Processing Integrity, Confidentiality, and Privacy.
- Ops: OpenTelemetry standardizes traces, metrics, and logs. k6 uses thresholds for pass/fail SLO-style load tests. Fly supports process groups, deploy health checks, and indirect worker health monitoring.

## Architecture Principle

Do not replace the existing honesty ledger. Extend it.

Every external integration run should produce a durable evidence row:

- `connector_id`
- `external_system`
- `mode`: `offline_csv`, `sandbox_api`, `live_readonly`, `live_write_draft`, `live_send`
- `api_name`
- `api_version`
- `tenant_hash`
- `credential_profile_id`
- `correlation_ids`
- `watermark`
- `idempotency_key`
- `source_record_count`
- `normalized_record_count`
- `rows_valid`
- `rows_invalid`
- `raw_payload_stored`
- `payload_sha256`
- `status`: `passed`, `partial`, `failed`
- `boundary_label`: `simulation`, `sandbox`, `live_readonly`, `draft_write`, `live_send`

Promotion rule:

`simulation -> exported-fixture replay -> vendor sandbox -> live read-only -> live draft write -> live send`

No connector can jump levels. The UI/API must label its level plainly.

## Workstream 1: Production-Scale Ops Proof

Build first because live integrations are useless if the platform cannot prove it runs reliably.

Implementation:

- Run the worker as a real Fly process group or separate Fly app.
- Set `WORKER_STRICT_HEALTH=1` after the worker heartbeat is reliable.
- Add deploy-time machine checks that verify database, Redis, worker heartbeat, migrations, and a small signed job execution.
- Move blobs from local `/data/blobs` to S3/R2/GCS-compatible object storage with encryption, signed URLs, retention policies, and backup/restore coverage.
- Add OpenTelemetry traces/metrics/logs for auth, uploads, CAD processing, connector runs, RFQ package creation, queue jobs, and webhooks.
- Add Prometheus/Grafana or equivalent dashboards and alerts for error rate, queue depth, stale jobs, worker heartbeat, DB latency, Redis latency, storage errors, and webhook retries.
- Add k6 load suites for login, upload/validate/cost, batch jobs, connector dry runs, RFQ package download, and admin health.
- Add 8-hour and 24-hour soak tests with concurrent orgs and realistic CAD/public corpus files.
- Add restore drills from production-like backups into staging and record RPO/RTO.

Acceptance:

- `/health` fails when Redis or expected worker is down.
- A real background job executes during deploy checks.
- Load tests pass thresholds, not just "ran."
- Restore drill has timestamped evidence and measured RPO/RTO.
- On-call runbook exists for deploy rollback, stuck workers, DB restore, leaked secret, and failed connector run.

## Workstream 2: Enterprise Identity: SSO, OIDC, SCIM

Implementation:

- Add `identity_connections` per org:
  - SAML metadata/cert/entity ID/ACS/SLO.
  - OIDC issuer/client/JWKS/discovery.
  - verified domains.
  - login policy.
  - break-glass accounts.
  - default role and group mapping.
- Harden SAML:
  - require signed assertions.
  - validate audience, recipient, ACS URL, issuer, time window, and replay IDs.
  - support certificate rotation and metadata import.
  - explicitly control IdP-initiated login.
- Add generic OIDC enterprise RP:
  - auth-code + PKCE where applicable.
  - strict `iss`, `aud`, `exp`, `nonce`, `kid`, JWKS validation.
- Add `/scim/v2`:
  - `/Users`
  - `/Groups`
  - `/ServiceProviderConfig`
  - `/Schemas`
  - `/ResourceTypes`
  - filtering, PATCH, idempotency, ETags where practical.
- Make SCIM the source of truth for enterprise org membership when enabled.
- On SCIM `active=false`, revoke sessions/API keys and remove org access immediately, while protecting the last admin and break-glass controls.

E2E proof:

- Okta sandbox creates user, assigns group, changes role, deactivates user.
- Microsoft Entra sandbox does the same.
- Browser sign-in verifies the right org and role.
- Deactivated user loses app/API access on next request.
- Audit export shows each lifecycle event.

Acceptance:

- Okta private SCIM and SSO tests pass.
- Entra non-gallery SAML/OIDC/SCIM tests pass.
- Negative tests for forged/replayed/expired assertions pass.
- Managed enterprise domains can require SSO and block password login except break-glass.

## Workstream 3: Connector Framework

Implementation:

- Create an adapter SDK:
  - `probe_credentials`
  - `discover_schema`
  - `extract`
  - `normalize`
  - `dry_run_diff`
  - `apply_draft`
  - `reconcile`
- Add per-org encrypted connector secrets.
- Add connector capability flags:
  - read-only
  - draft-write
  - live-send
  - attachment upload
  - webhook receive
- Add idempotency and external ID mapping tables.
- Add connector-run evidence export.
- Keep raw payload storage disabled by default.

Acceptance:

- Every connector can dry-run without mutating external systems.
- Duplicate external IDs reconcile safely.
- All connector failures are visible in the run ledger.
- Secrets never appear in logs, screenshots, reports, or exports.

## Workstream 4: SAP / ERP

First target: SAP S/4HANA read-only Product/BOM/demand/actuals sandbox.

Implementation:

- Start with SAP sandbox or customer-provided nonproduction tenant.
- Read Product/Material, BOM header/item, plant/program, demand, and actual/quote data where API access permits.
- Normalize into CadVerify manifest/part-context/ground-truth objects.
- Add schema versioning for exported SAP CSV fallback.
- Build reconciliation reports:
  - source item count vs normalized item count.
  - material/revision/quantity mismatch.
  - missing plant/program context.
  - cost actuals vs should-cost estimate.

E2E proof:

- Pull a known SAP product/BOM from sandbox.
- Match a CAD/STEP part in CadVerify.
- Run cost/validation.
- Produce discrepancy report and connector-run evidence.

Acceptance:

- Source BOM count, revisions, quantities, and plant filters match.
- Run is repeatable and idempotent.
- No live write occurs in read-only mode.
- "SAP connected" label appears only after a successful sandbox/live connector run.

## Workstream 5: PLM / CAD / BOM

First target: PTC Windchill read connector. Secondary targets: Autodesk APS/Fusion Manage or Siemens Teamcenter depending on accessible sandbox/customer stack.

Implementation:

- Define normalized PLM objects:
  - `ExternalPart`
  - `ExternalPartRevision`
  - `ExternalBomNode`
  - `ExternalDocument`
  - `ExternalCadRepresentation`
  - `LifecycleState`
- Read part, revision, BOM, quantity, occurrence, material, document/CAD representation, lifecycle state.
- Support STEP derivative download only when explicitly allowed.
- Preserve exact source revision and source URL/reference in provenance.
- Use public CAD corpora before customer data:
  - NIST AM-Bench STEP/STL data.
  - ABC dataset STEP/Parasolid/STL corpus.
  - curated mechanical component fixtures.

E2E proof:

- Pull a PLM part + BOM + STEP derivative.
- Verify part displays and interacts correctly in the browser.
- Verify service environment/context appears correctly in cost and RFQ artifacts.
- Compare part hash, filename, revision, and BOM evidence end-to-end.

Acceptance:

- CAD render is nonblank and inspectable in Playwright screenshots.
- Part/revision/BOM provenance survives through cost decision and RFQ package.
- No native CAD conversion claim unless the needed converter/license is actually installed and tested.

## Workstream 6: Procurement / RFQ

Implementation:

- Turn RFQ package export into a real workflow:
  - draft
  - internal review
  - approval
  - ready to send
  - sandbox sent/draft created
  - supplier response received
  - closed / no-bid / awarded
- Add approval matrix:
  - role thresholds.
  - dual approval for high spend.
  - stale-cost invalidation.
  - audit trail.
- Add supplier directory:
  - contacts.
  - capabilities.
  - allowed processes/materials.
  - NDA/export-control flags.
  - preferred channel.
- Integrate first in safe modes:
  - cXML sandbox/order/RFQ-style handoff.
  - Coupa supplier/procurement sandbox where credentials exist.
  - SAP Ariba/Sourcing sandbox only where API capability and account access exist.
- Use outbox + kill switch + explicit approval for any outbound write/send.

E2E proof:

- Generate RFQ from approved cost decision.
- Route approval.
- Create sandbox draft/send to mock or sandbox endpoint.
- Receive supplier response.
- Compare supplier quote to CadVerify should-cost and record result.

Acceptance:

- Live supplier send is disabled until a named connector has passed sandbox and live draft gates.
- Every outbound package has an immutable hash and manifest.
- Supplier response ingestion cannot overwrite original evidence.

## Workstream 7: Security Audit and SOC2 Readiness

Implementation:

- Build an OWASP ASVS v5 matrix mapped to code/tests.
- Run OWASP WSTG-based manual and automated web security testing.
- Run SAST, dependency scanning, secret scanning, IaC scanning, container scanning, and DAST.
- Add tenant-isolation tests for every sensitive object type.
- Add abuse tests:
  - broken access control.
  - forged org ID.
  - stale session.
  - revoked API key.
  - SAML replay.
  - SCIM unauthorized mutation.
  - connector secret exposure.
- Create SOC2 evidence binder:
  - change management.
  - access control.
  - backups/restore.
  - incident response.
  - vendor risk.
  - monitoring.
  - vulnerability management.
  - data retention/deletion.
- Engage external pen-test firm after internal high/critical issues are closed.

Acceptance:

- Zero open critical/high vulnerabilities or documented executive risk acceptance.
- External pen-test report is remediated or exceptioned.
- SOC2 readiness packet exists before claiming SOC2 readiness; Type I/II claims require actual auditor engagement.

## Workstream 8: Human-Simulated E2E QA

This is the user's core testing requirement.

Surfaces:

- Production web app.
- Local/staging web app.
- Admin/ops endpoints.
- API clients.
- Future mobile/desktop only if those surfaces exist.

Branch tree:

- anonymous visitor.
- signup/login/logout.
- password auth.
- SSO auth.
- SCIM-provisioned user.
- deprovisioned user.
- org admin.
- viewer.
- CAD engineer.
- procurement reviewer.
- supplier/RFQ reviewer.
- SAP connector admin.
- PLM connector admin.
- security/auditor.
- failed upload.
- valid STEP upload.
- bad CAD file.
- missing context.
- service-environment context.
- stale cost decision.
- approved cost decision.
- RFQ package.
- connector dry run.
- connector import.
- connector failure/retry.

Acceptance:

- Playwright tests operate the real UI, not just APIs.
- Screenshots and console/network logs are captured.
- Output fidelity tests verify input correctness, methodology honesty, calculation correctness, display correctness, and interaction correctness.
- Production canary exercises a non-destructive subset after deploy.

## Orchestrator / QA / QC Operating Model

The orchestrator should run work as lanes, then block promotion until independent QA/QC passes.

Agent lanes:

- Identity Agent: SAML/OIDC/SCIM.
- Connector Agent: adapter SDK, SAP, PLM.
- Procurement Agent: RFQ approval and cXML/Coupa/Ariba modes.
- Security Agent: ASVS/WSTG/SOC2/pen-test packet.
- SRE Agent: worker, object storage, load, restore, observability.
- QA Agent: Playwright human-simulated journeys and evidence binder.

QA/QC layers:

1. Builder self-test: unit/integration tests written before/with implementation.
2. Peer code review: separate agent reviews diff for bugs/security.
3. Human-simulated E2E: Playwright drives the web app through branch tree.
4. Adversarial tests: auth bypass, tenant isolation, replay, revoked access, malformed CAD, connector failures.
5. Sandbox certification: Okta/Entra/SAP/PLM/procurement sandbox proofs.
6. Production canary: safe live checks after deploy.
7. Evidence binder: signed summary of every gate with logs/artifact paths.

## Phased Build Plan

### Phase 0: Decision Lock

Duration: 1-2 days.

Decide:

- First IdP: Okta and Entra both required; choose first implementation order.
- First ERP: SAP S/4HANA sandbox or exported fixtures.
- First PLM: PTC Windchill if sandbox/account exists; otherwise Autodesk APS/Fusion Manage public path.
- First procurement path: cXML sandbox/mock plus Coupa or Ariba depending on reachable credentials.
- First CAD corpus: NIST AM-Bench + ABC subset.

Deliverable:

- `outputs/enterprise-proof-matrix.md`
- connector promotion policy.
- updated current-state map.

### Phase 1: Ops Truth Gate

Duration: 3-5 days.

Build:

- worker process group.
- strict worker health.
- deploy machine check.
- object storage path.
- OTel instrumentation starter.
- k6 threshold suite starter.

Gate:

- production health fails truthfully when worker is absent.
- staging load/restore pass.

### Phase 2: Identity Lifecycle

Duration: 1-2 weeks.

Build:

- identity connection model.
- SAML hardening.
- generic OIDC.
- SCIM v2 Users/Groups.
- managed-domain SSO enforcement.
- audit export.

Gate:

- Okta and Entra sandbox lifecycle passes.

### Phase 3: Connector SDK + SAP/PLM Read-Only

Duration: 2-4 weeks.

Build:

- connector SDK and evidence ledger expansion.
- SAP read-only adapter.
- PLM read-only adapter.
- exported fixture replay harness.

Gate:

- real sandbox or approved exported fixture runs pass with reconciliation.

### Phase 4: Procurement/RFQ Workflow

Duration: 2-3 weeks.

Build:

- RFQ workflow state machine.
- approval matrix.
- supplier directory.
- immutable outbound package.
- cXML/Coupa/Ariba sandbox connector mode where access exists.

Gate:

- sandbox draft/send/response proof passes with no accidental live supplier contact.

### Phase 5: Security Audit Readiness

Duration: parallel, 2-4 weeks.

Build:

- ASVS matrix.
- WSTG test plan.
- tenant isolation suite.
- DAST/SAST/dependency/container/IaC scans.
- SOC2 evidence binder.

Gate:

- no open critical/high internal findings.
- external pen-test ready.

### Phase 6: Production-Scale Proof

Duration: 1-2 weeks after core flows are stable.

Build:

- 8-hour and 24-hour soak.
- production-safe canary.
- backup/restore proof.
- alert drills.
- rollback drill.

Gate:

- evidence binder says the platform meets defined SLOs and recovery objectives.

## First Implementation Tickets

1. Add `connector_runs_v2` metadata fields and promotion boundary labels.
2. Add Fly worker process and set up worker heartbeat evidence.
3. Turn on strict worker health in staging, then production after heartbeat proves stable.
4. Add object storage abstraction for batch blobs and RFQ packages.
5. Add SCIM database tables and `/scim/v2/ServiceProviderConfig`.
6. Implement SCIM `/Users` create/read/update/PATCH/deactivate.
7. Implement SCIM `/Groups` and role mapping.
8. Add managed-domain SSO enforcement and break-glass policy.
9. Add connector SDK skeleton with exported-fixture replay.
10. Add SAP S/4HANA read-only sandbox adapter behind feature flag.
11. Add Windchill read-only adapter behind feature flag.
12. Add RFQ approval state machine and immutable package hash.
13. Add cXML sandbox/mock endpoint and outbound outbox.
14. Add ASVS evidence matrix and tenant-isolation adversarial tests.
15. Add k6 production-safe canary and soak scripts.

## Sellable Claim Ladder

Allowed now:

- Deployed production web app.
- Simulated enterprise QA.
- Offline CSV SAP/PLM-style import proof.
- RFQ evidence-package proof.

Allowed after Phase 2:

- Enterprise identity lifecycle tested with Okta/Entra sandboxes.

Allowed after Phase 3:

- SAP/PLM sandbox connector proof.
- Live read-only connector proof only for named systems where a successful run exists.

Allowed after Phase 4:

- Procurement/RFQ sandbox proof.
- Live draft procurement proof only if explicitly tested in a nonproduction tenant.

Allowed after Phase 5/6:

- Security-audit-ready and production-scale-proof-ready.

Not allowed until external evidence exists:

- SOC2 certified.
- Pen-test passed.
- Exxon certified.
- SAP/Ariba/Coupa/PTC/Siemens certified.
- Live supplier network proven.
- Fully enterprise-certified.

## Primary Sources

- OASIS SAML 2.0 Technical Overview: https://docs.oasis-open.org/security/saml/Post2.0/sstc-saml-tech-overview-2.0.html
- IETF RFC 7644 SCIM Protocol: https://datatracker.ietf.org/doc/html/rfc7644
- Okta SCIM provisioning integration guide: https://developer.okta.com/docs/guides/scim-provisioning-integration-overview/main/
- Microsoft Entra SSO overview: https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/what-is-single-sign-on
- Microsoft Entra SAML setup/testing: https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/add-application-portal-setup-sso
- SAP Integration Suite: https://www.sap.com/products/technology-platform/integration-suite.html
- SAP Business Accelerator Hub: https://hub.sap.com/
- PTC Windchill REST Product Management Domain: https://support.ptc.com/help/windchill_rest_services/r2.4/en/windchill_rest_services/prodmgmtdomain.html
- PTC Windchill BOM read example: https://support.ptc.com/help/windchill_rest_services/r2.6/en/windchill_rest_services/WCCG_RESTAccessExamplesReadBOM.html
- Autodesk Platform Services Data Management API: https://aps.autodesk.com/data-management-api
- cXML official resources: https://cxml.org/
- Coupa Suppliers API: https://compass.coupa.com/en-us/products/product-documentation/integration-technical-documentation/the-coupa-core-api/resources/reference-data-resources/suppliers-api-%28suppliers%29
- OWASP ASVS: https://owasp.org/www-project-application-security-verification-standard/
- OWASP WSTG: https://owasp.org/www-project-web-security-testing-guide/
- NIST SP 800-115: https://csrc.nist.gov/pubs/sp/800/115/final
- AICPA Trust Services Criteria: https://www.aicpa-cima.com/resources/download/2017-trust-services-criteria-with-revised-points-of-focus-2022
- OpenTelemetry docs: https://opentelemetry.io/docs/
- Grafana k6 API load testing: https://grafana.com/docs/k6/latest/testing-guides/api-load-testing/
- Fly process groups: https://fly.io/docs/launch/processes/
- Fly health checks: https://fly.io/docs/reference/health-checks/
- Google SRE SLOs: https://sre.google/workbook/implementing-slos/
- NIST AM-Bench: https://www.nist.gov/ambench
- ABC CAD Dataset: https://deep-geometry.github.io/abc-dataset/

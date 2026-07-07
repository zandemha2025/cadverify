# Champion Packet Protocol

Purpose: define the evidence packet a real enterprise pilot must fill before CadVerify may claim validated accuracy, enterprise IT acceptance, production operations readiness, or live integration proof.

This file is a protocol, not proof by itself. Until the packet is filled with real customer systems and signed evidence, the platform state remains "apparatus built; external proof pending."

## Non-Negotiable Truth Boundary

- `validated=true` is earned only from real quote/actual/hour evidence tied to a real shop, real material, real process, real geometry family, and real order context.
- Synthetic fixtures, seeds, demos, local test runs, generated screenshots, and mock integrations must remain `validated=false`.
- Offline CSV dry-runs prove parser/ledger behavior only. They do not certify SAP, ERP, PLM, supplier, IdP, SCIM, SOC 2, pen-test, restore, load, or procurement readiness.
- Each packet item needs an owner, date, evidence link or artifact path, and pass/fail disposition.

## Packet Metadata

Required fields:

- Customer / pilot organization:
- Site / division:
- Pilot owner:
- CadVerify owner:
- Packet started:
- Packet completed:
- Target release / commit SHA:
- Deployment environment:
- External systems exercised:

## Domain 1 - Validated Accuracy

Required evidence:

- Real CAD corpus list, with each file classified by format, process, material, geometry family, and confidentiality handling.
- Real quote/actual/hour import artifact, including source system, timestamp, units, currency, and evidence URI.
- Calibration run output showing residual/error by process, material, geometry family, shop, and volume.
- Evidence that all synthetic/demo rows remain `validated=false`.
- Approval record from an accountable customer-side manufacturing/cost owner.

Minimum pass criteria:

- No synthetic row can set `validated=true`.
- Real rows include enough source metadata to reproduce the validation claim.
- Residuals and confidence bands are visible to the evaluator, not hidden behind a single score.

## Domain 2 - CAD Breadth

Required evidence:

- STEP/STL/IGES happy-path files processed end to end.
- Unsupported native CAD, drawings, assemblies, corrupt files, huge files, and non-watertight files triaged with explicit user-facing reasons.
- PMI/GD&T and drawing scope documented as parsed, declared, or unsupported for each corpus item.
- Failure artifacts for every rejected file class.

Minimum pass criteria:

- Unsupported files never collapse into fake cost results.
- Each rejection tells the evaluator what is missing and whether there is a supported next step.

## Domain 3 - Enterprise IT And Security

Required evidence:

- Live IdP SAML login with group-role mapping exercised by at least admin and non-admin users.
- Offboarding/session revocation test showing stale sessions fail closed.
- SCIM or lifecycle provisioning result, or explicit customer-approved deferred status.
- Tenant isolation test result.
- Security questionnaire, SOC 2 status, retention policy, audit export posture, and pen-test handoff/result.

Minimum pass criteria:

- A removed or downgraded user cannot keep using the platform.
- Tenant-scoped data is not visible across org boundaries.
- Any deferred enterprise-security requirement is signed off as a known gap.

## Domain 4 - Production Operations

Required evidence:

- Deployed commit SHA and environment configuration.
- CI run URL for the commit under evaluation.
- Backup and restore drill output.
- Migration rollback or forward-fix drill output.
- Worker failure recovery evidence.
- Queue health and alerting evidence.
- Load/soak result for a representative catalog and CAD workload.
- Incident runbook/SLO review.

Minimum pass criteria:

- The team can restore data and explain the recovery point/time.
- Worker and queue failures are visible and recoverable.
- Load testing reports real limits, not marketing targets.

## Domain 5 - Enterprise Workflow

Required evidence:

- First-run onboarding through machine floor declaration/import.
- Cost decision approval, reopen, stale-warning, and export flow.
- RFQ evidence package creation and download from approved/stale decision cases.
- Notification read/read-all behavior.
- Role-specific journeys for CAD engineer, cost engineer, sourcing/procurement, org admin, and ops/admin.

Minimum pass criteria:

- Workflow state changes persist and are visible in history/audit surfaces.
- Stale or unapproved decisions carry warnings into exports/RFQ evidence.
- Role boundaries match the customer operating model.

## Domain 6 - Real Integrations

Required evidence:

- SAP/ERP import/export exercised against a customer-approved sandbox or live test tenant.
- PLM connector strategy exercised or explicitly deferred.
- Quote/actual customer feed harness run against a real customer feed sample.
- Versioned API contract and backward-compatibility result.
- Supplier/RFQ send workflow if in scope; otherwise evidence-package-only boundary acknowledged.

Minimum pass criteria:

- No live credential is stored or displayed improperly.
- Customer feed rows produce reproducible ledger records.
- Any non-certified connector is labeled apparatus-only.

## Domain 7 - Human-Sim QA

Required evidence:

- Browser journey artifacts for each role: CAD engineer, cost engineer, sourcing/procurement, org admin/security, ops/admin.
- Failure journey artifacts: invalid CAD, huge CAD, unsupported CAD, timeout, worker down, rate limit, expired invite, stale rate card, low-role denial.
- Screenshots, JSON report, and command log for each run.
- Rubric score: data-true, environment-correct, drillable, conversational, recoverable.

Minimum pass criteria:

- Medium-or-higher QA issues are fixed or explicitly accepted by the pilot owner.
- Browser evidence uses the same build/commit as the packet metadata.

## Signoff

Required signoffs:

- Customer manufacturing/cost owner:
- Customer IT/security owner:
- Customer ops/procurement owner:
- CadVerify engineering owner:
- CadVerify product owner:

Final status:

- `PASS`: all required evidence is present and accepted.
- `PASS_WITH_ACCEPTED_GAPS`: gaps are listed with owner/date/follow-up.
- `FAIL`: one or more required evidence items is missing, false, or not accepted.

The default status is `FAIL` until filled evidence proves otherwise.

# CadVerify Enterprise Finish-Line DAG

Authoritative scope: seven Real Finish Line domains from the attached spec.

## Non-Negotiable Guardrail

`validated=true` is a real-world earned state. It must not be produced by synthetic fixtures, seed records, demo flows, load harnesses, or generated examples.

## Phase Graph

```text
P0 Control plane and current-state map
  -> P1 Validated-accuracy apparatus
  -> P2 CAD breadth and honest corpus triage
  -> P3 Enterprise IT acceptance apparatus
  -> P4 Production operations apparatus
  -> P5 Enterprise workflow completeness
  -> P6 Real integrations apparatus
  -> P7 Human-sim QA expansion
  -> P8 Champion packet protocol and terminal handoff
```

P7 runs throughout and gates the phases it touches.

## Phase Definitions

### P0 - Control Plane and Current-State Map

Deliverables:
- Build log, decision log, handoff queue, phase DAG.
- Current-state maps for P1-P7.
- Fresh task decomposition with disjoint ownership.

Gates:
- Domain scouts complete or coordinator-owned map exists.
- Human/real-system dependencies are queued, not blocked.

### P1 - Validated-Accuracy Apparatus

Deliverables:
- Quote/actual/hour import path and schema audit.
- Residual/error analysis by process, material, geometry family, shop, and volume.
- Calibration/band surfaces that remain unvalidated on synthetic data.
- Pilot-report generator and champion packet input template.
- Tests proving synthetic data cannot set `validated=true`.

Gates:
- Unit/integration tests for import, residuals, calibrated bands, and validation guard.
- Browser or report-generation evidence on seeded data with `validated=false`.

### P2 - CAD Breadth and Honest Corpus Triage

Deliverables:
- Deploy-parity STEP/IGES proof and parser failure artifacts.
- Unsupported native-CAD/drawing/assembly strategy and honest triage buckets.
- Declared-spec workflow for PMI/GD&T gaps.
- Multi-body, sheet-metal, weldment, and non-watertight handling strategy in corpus triage.

Gates:
- Parser tests and corpus triage tests never silently collapse unsupported files.
- E2E journey covers invalid/unsupported/huge CAD failure states.

### P3 - Enterprise IT Acceptance Apparatus

Deliverables:
- Live-SSO-ready SAML setup plus group-role mapping and domain/org provisioning apparatus.
- SCIM or lifecycle endpoint strategy and offboarding/session revocation coverage.
- Audit retention/export posture and security questionnaire packet.
- Tenant isolation tests and pen-test handoff checklist.

Gates:
- Tests for offboarding, role mapping, session revocation, and tenant isolation.
- Handoff queue records live IdP and external pen-test dependencies.

### P4 - Production Operations Apparatus

Deliverables:
- CI on actual branch, deploy-image verification, Docker/Helm proof, backup/restore drill, migration rollback drill.
- Observability, queue health, worker failure recovery, object storage strategy.
- Synthetic big-catalog load/soak harness.
- SLO and incident runbook.

Gates:
- CI jobs or local scripts run against synthetic infrastructure.
- Restore/migration/load scripts are executable and documented.

### P5 - Enterprise Workflow Completeness

Deliverables:
- First-run onboarding for machine floor import/declaration.
- Bulk/BOM/manifest UI, Programs as first-class workflow, decision signoff, stale-decision detection.
- Verification-record export/PDF, notifications/inbox.
- Governed shop certifications and process specs.
- Deterministic ask-the-engine what-if/why interface.

Gates:
- Role E2E journeys cover viewer, analyst, org admin, and superadmin paths where available.
- Browser + API assertions verify workflow correctness.

### P6 - Real Integrations Apparatus

Deliverables:
- SAP/ERP import/export bridge, PLM connector strategy, quote/actuals ingestion contract.
- Supplier/RFQ bridge decision and scoped implementation if in-product.
- Versioned API docs and customer feed test harness.

Gates:
- Integration harness runs with synthetic feeds.
- Real-feed exercise remains in handoff queue.

### P7 - Human-Sim QA Expansion

Deliverables:
- Role journeys: viewer, analyst, org admin, superadmin.
- Failure journeys: invalid CAD, huge CAD, timeout, worker down, rate limit, expired invite, stale rate card.
- Browser + API cross-checks and screenshot/video artifacts.
- Seeded O&G, aerospace, automotive, medical scenarios.
- Drop-audit rubric score: cinematic, data-true, environment-correct, drillable, conversational.

Gates:
- CI publishes artifacts.
- Any medium-or-higher QA issue fails the gate.

### P8 - Champion Packet Protocol

Deliverables:
- `outputs/champion-packet-protocol.md`.
- Template for the customer evidence packet.
- Exact fill-in requirements for real pilot data, live SSO, pen test, SOC 2, real load/soak, real deploy/restore, and required credentials/access.

Gates:
- States plainly that nothing is validated or enterprise-exercised until real systems prove it.

# CadVerify Real-System Handoff Queue

This queue contains dependencies that cannot be truthfully completed by code alone. The build should create apparatus, self-tests, fixtures, protocols, and docs for each item, but the status remains pending until exercised against real systems or real data.

## Handoff Items

| ID | Domain | Dependency | What the build can provide | Completion requires |
| --- | --- | --- | --- | --- |
| H-001 | P1 validated accuracy | Real customer quotes, actual costs, machine hours, outcomes | Importers, validation ledger, residual dashboards, pilot-report generator, guardrail tests | Customer pilot data and signed-off run |
| H-002 | P2 CAD breadth | Real customer CAD corpus | Corpus triage harness, unsupported-format buckets, parser probes, failure artifacts | Customer corpus access |
| H-003 | P2 CAD breadth | Native CAD conversion | Strategy doc, adapter interface, test fixtures for declared unsupported states | Licensed converter or customer export workflow |
| H-004 | P3 enterprise IT | Live Okta/Entra/Ping tenant | SAML config, group-role mapping code, test harness, setup docs | IdP admin access and live login/offboarding test |
| H-005 | P3 enterprise IT | Pen test | Threat model, test accounts, isolation checklist, security packet | Third-party firm execution |
| H-006 | P3 enterprise IT | SOC 2 evidence | Control/evidence roadmap and generated artifacts | Auditor engagement |
| H-007 | P4 operations | Real cloud deploy and restore drill | Scripts, runbook, synthetic-data drill, CI job | Target cloud credentials and real infra run |
| H-008 | P4 operations | Real-scale load/soak | Synthetic large-catalog harness and thresholds | Real catalog and production-like hardware |
| H-009 | P6 integrations | SAP/ERP/PLM feeds | Connector registry, run ledger, CSV/API bridge, `/integrations` operator surface, parser-backed dry-run/import tests | Customer system access or exported feed samples |
| H-010 | P5 workflow | Production signoff authority and SOP | Approval/reopen/staleness apparatus, UI, API, tests | Customer-defined approver roles, operating procedure, and live record review |
| H-011 | P4/P6 operations | Remote object batch input | Stable 501 rejection and no-orphan tests | Object-fetch adapter, storage credentials, worker fetch proof, and failure-mode E2E |
| H-012 | P2 CAD breadth | SAM-3D operational segmentation | Modular pipeline scaffold, disabled availability gate, fallback worker behavior | Real face-ID renderer, model weights, GPU/dependency image, and corpus proof |
| H-013 | P2 CAD breadth | Image-to-mesh reconstruction | Zero-egress availability checks, local/remote backend guardrails, structured 501 | Local model install or explicit remote-egress approval plus live reconstruction proof |

## Status

All items are pending real-system exercise. None may be described as completed or enterprise-exercised until the listed completion requirement is met.

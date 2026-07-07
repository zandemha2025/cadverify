# CadVerify Enterprise Build Decisions

Authoritative scope: the Real Finish Line attachment.

## Locked Decisions

### D-001: The finish-line spec supersedes stale planning docs

The April `.planning/ROADMAP.md` and `.planning/STATE.md` are useful historical context, but the active scope is the seven-domain Real Finish Line spec. New work is planned against that spec.

### D-002: Proof apparatus precedes polish

The first build wave prioritizes validation ledger, residual analysis, pilot-report apparatus, guardrail tests, and honest deferrals. Product polish proceeds only after proof machinery cannot be confused with proof itself.

### D-003: Synthetic data can exercise the machine but cannot validate it

Seed and fixture data may drive dashboards, E2E journeys, load harnesses, and pilot-report templates. They must leave `validated=false` and must be visibly marked as synthetic or unvalidated.

### D-004: Real-system dependencies defer to handoff, not blockers

Live Okta/Entra/Ping, real SAP/PLM feeds, pen-test firms, SOC 2 auditors, real customer corpora, real cloud infrastructure, and customer credentials are recorded in `outputs/handoff-queue.md`. The code apparatus and self-tests are still built.

### D-005: Agent orchestration uses disjoint ownership

Sub-agents may inspect broadly, but code-writing waves must own disjoint file sets. The coordinator integrates, reviews, tests, and commits.

### D-006: QA/QC is layered, not one final test run

Every build slice needs builder checks, independent verifier review where practical, guardrail tests, and human-sim browser coverage when it touches product behavior.

### D-007: Unsupported CAD-like files are visible terminal outcomes

Non-CAD noise in a ZIP may be ignored, but native CAD and drawing formats are CAD-adjacent enterprise inputs. They become `skipped` batch items with explicit reasons and count as terminal failures for progress math.

### D-008: Container proof is a CI claim until Docker exists locally

This environment cannot run Docker. Local work may statically verify Docker/Compose configuration, but image-build proof is only claimed where CI runs Docker.

### D-009: Role/failure human-sim QA is part of the full E2E gate

The P7 role/failure runner is wired into `npm run test:e2e:full`. Standalone unavailable-app runs write an explicit `SKIPPED_UNAVAILABLE` report; CI runs it after the app is started, where failures are real gates.

### D-010: Saved decisions are immutable; governance is additive metadata

Approvals, reopenings, and stale markers do not rewrite `result_json`. They add review/currentness metadata around the saved glass-box artifact so historical RFQ/source records remain auditable while current-use warnings can change.

### D-011: Dashboard sessions are stateless tokens with DB-backed version revocation

CadVerify keeps cheap HMAC dashboard cookies, but the signed body carries `users.session_version`. Revocation increments the user-row version; validation rejects stale cookies. Pre-0028 cookies parse as version `0` until the first explicit revocation.

### D-012: P6 starts with offline connector apparatus, not fake live SAP/PLM

Until real customer SAP/PLM credentials exist, the enterprise integration slice is a connector registry plus import-run ledger over CSV exports. Runs must record source system, file hash, row counts, errors, and status without storing raw CSV by default.

### D-013: Notifications are workflow state, not compliance history

Durable inbox rows may be read, resolved, reopened, and routed to UI surfaces. They do not replace audit logs, verification records, saved cost decisions, webhook ledgers, or validation ledgers as source-of-truth evidence.

### D-014: Real CAD fixtures must run when present

If the repo contains a real fixture archive, accuracy and gate suites should resolve and run it instead of skipping because a stale scratchpad directory exists. Synthetic substitutes remain forbidden for validation claims.

### D-015: Integration runs store evidence, not raw customer feeds

Offline SAP/PLM/actuals connector runs persist source system, connector, file hash, row counts, errors, and status. Raw CSV payloads are not stored by default; live integration claims require real credentials or customer-provided feed samples.

## Pending Decisions

- Scope of supplier/RFQ bridge: system-of-record boundary versus last-mile execution.
- First live identity provider for SSO exercise: Okta, Entra ID, or Ping.
- First customer-data bridge beyond CSV: SAP export, PLM export, or neutral ingestion API first.
- Native CAD strategy: direct translation library, customer-side export requirement, or commercial converter integration.

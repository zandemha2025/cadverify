# CadVerify — Coverage-to-100 Campaign (Fable-directed)

**Goal:** drive the ENTIRE product e2e (all 12 workflows × the persona set × the 12
Bucket-A categories), repair every finding, and reach a real **Product overall = 100**
(the MIN across Bucket-A categories) with screenshot evidence — or an honest Bucket-B
gate for the few things that genuinely need external systems. No inflation; a fake 100
is the only failure.

**Orchestration:** Fable (this main loop) plans + directs. Each wave spawns bounded
live-stack persona sub-agents (≤2 concurrent — own ports/DB/browser, honest latency),
collects findings, fans out repair-builders (lighter, wider), then Fable gates
(full suite + build) + integrates + re-verifies before the next wave. Loop until done.

## Definition of done
- Every Bucket-A category scores a real 100 on evidence, across ALL 12 workflows +
  the persona set (new, returning, admin, member, read-only, empty vs populated org).
- Every finding is fixed + re-verified on screen, and logged permanently in the registry.
- Coverage ledger shows 12/12 workflows driven, categories no longer "partial".
- Bucket B (live SSO/SAP tenants, SOC2/pentest, accuracy-vs-real-data) labeled honestly —
  never counted into the Product MIN, never faked to 100.

## Coverage matrix — remaining to drive (5/12 already deep: W1,W2,W3,W11,W12)
| Wave | Workflows / focus | Persona | Ports/DB |
|---|---|---|---|
| A | W4 bulk manifest → triage · W5 machines → makeability + gap | P2 sourcing · P3 shop owner | 8043/3043 · 8044/3044 |
| B | W6 portfolio exposure · W7 ground-truth / calibration flywheel | P2 · P5 CFO | 8045/3045 · 8046/3046 |
| C | W8 save/export/share/PDF · W9 RFQ supplier package | P1 · P2 | 8047/3047 · 8048/3048 |
| D | W10 org → invite → SSO/SCIM admin (also exercises Security + roles) | P4 admin + a 2nd member/read-only user | 8049/3049 |
| E | Dedicated category deep-dives: Security (cross-tenant + non-admin), Error-recovery (failure injection), Accessibility (full audit) | adversarial | 8050/3050 |
| F | Re-score everything + verify Product MIN = 100 (or honest gate) | full sweep | fresh |

## Category-100 bar (Bucket A)
Functional, Data, AI, Interaction, Visual, Performance, Reliability, Error-recovery,
Security, Accessibility, Regression — each needs every driven flow to pass with evidence.
Conversational = N/A (no chat) unless a chat surface is found. Performance is measured on
a QUIET run (not while 2 personas contend) so the ms are honest.

## Loop discipline (every wave)
1. Persona sub-agents drive REAL flows (RUNBOOK recipe, vision, screenshots), score, file
   findings in the schema. 2. Fable synthesizes + ranks. 3. Repair-builders (bounded
   parallel) fix; each gated on full suite + build. 4. Integrate + re-verify the finding on
   screen. 5. Update REGISTRY + COVERAGE. 6. Next wave. Nothing merges on a builder's word.

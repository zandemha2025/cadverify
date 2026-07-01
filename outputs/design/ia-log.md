# IA & Flows — Strategist/Architect Log

## DONE (2026-06-29)

Deliverable written: outputs/design/ia-and-flows.md (589 lines).
Grounded in: audience.md (5 segments + opposing-needs matrix T1-T8), design-landscape.md (adopt/avoid),
design-direction.md (locked north star), and the REAL engine outputs — verified by running the cost CLI
and reading the report_to_dict JSON sidecar (drivers+provenance, confidence, routing, decision/crossover,
per-shop calibration Midwest vs Shenzhen). Built ON the existing AppShell + part-as-object workspace +
answer-first CostDecisionView (kept), elevated to role-aware glass-box IA.

Core structural moves: 3 primitives (Analysis Object · Role Lens · Universal drill-down); 3 IA zoom layers
(global nav · part workspace · drill-down); 5 surfaces (Decision · Glass Box · Routing & DFM · Compare ·
Share/Handoff) + Calibration topbar context + Portfolio roll-up; Role Lens routes all 5 segments to a
named landing. Flow map F0-F6 (master upload→routing→glass-box→calibrate→decision, tweak-rerun,
override&audit, compare/make-vs-buy, verify-routing, designer→purchaser handoff, buyer trust/roll-up).
Reachable states designed; positioning↔design bridge mapped claim→structure; honesty rail enforced
(no fabricated ±X%; confidence.validated wired to "assumption-based, not yet validated").

Acceptance self-audit in §11 passes all three criteria. API/build gaps flagged in §10 (engine emits
everything; exposure/persistence is build-harness work). No blockers.

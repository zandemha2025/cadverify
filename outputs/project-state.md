# CadVerify — Project State (Harness)

**Run started:** 2026-06-28 · **Target tier:** ZOOX-GRADE
**Position:** Cycles 1–5 COMPLETE & independently verified · **STOP = DONE-PENDING-GATES** (see `outputs/FINAL-HANDOFF.md`) · Cycles used: 5/6

## Definition of Done — status

### [buildable]
- [x] **Honest teardown on real parts vs CASTOR/3D Spark/aPriori** — C1
- [x] **Decision layer V0 demoable on real parts** (cost + lead time + crossover + make-vs-buy) — C1
- [x] **Decision layer V1** — all 8 weaknesses fixed; coherent; driver-traceable — C2/C3
- [x] **Cost-data source-of-truth wired, transparent/traceable** — C2 (option b: user rates + MEASURED/USER/DEFAULT provenance; Σ-invariant enforced)
- [x] **Accuracy-validation harness w/ MEASURED error bands** — C2/C3 (CNC/IM/powder-bed in band; serial-AM fixed C3; honest residuals documented)
- [x] **Output/report + API** — C3 (`POST /api/v1/validate/cost`, auth+kill-switch+structured errors, no persistence, zero egress)
- [x] **Process-routing ground-truth system** (NEW, added C4) — 667-part licensed corpus + `/label` tool + routing-accuracy & k-NN similarity eval harness. *Real metrics gated on human labels.*
- [x] **CAD ingestion robustness** — C5: STEP→mesh via gmsh works end-to-end (real LGPL file → cost decision); STL untouched. *B-rep/GD&T/AP242 + IGES = env-gated (cadquery/OCP) → handoff G5.*
- [x] **Productionization** — C5: structured request-id logging (no CAD/secret leak), structured errors (+501), caps/timeouts (STEP off-loop, 504), zero egress, CAD-as-IP; **frontend `/cost` decision surface**; **500 backend tests pass / 5 env-gated skips**. *Encryption-at-rest/tenant-isolation/VPC = deploy-time → handoff G8.*

### [gate] (no cycle closes these — FINAL HANDOFF)
- [GATE · ACTIVE] **Human expert validation — Zoox Head of Manufacturing demo** (artifact: `outputs/validation-packet.md`, now V1-coherent)
- [GATE · ACTIVE] **Human labeling — ≥30 real manufacturing-method labels** via `/label` (ideally by a manufacturing person) before routing-accuracy metrics are real
- [GATE] Security audit / SOC 2 / pen test · Export/ITAR + Saudi data-residency · On-prem/VPC acceptance · Procurement/MSA · Cost-data/supplier licensing (if pursued) · Wedge/pricing go-no-go

## Test coverage (independently re-run)
Costing 48 (model 14 + accuracy 10 + gates 16 + cost_api 8) + eval 15 + API/auth ~17 = **80+ passing**.

## What exists now (working tree, uncommitted)
`backend/src/costing/` (decision layer) · `backend/src/eval/` + `backend/src/corpus/` + `backend/src/api/corpus_router.py` (labeling) · `frontend/src/app/label/` (label tool) · `data/corpus/` (667 parts, gitignored) · `outputs/` (all deliverables).

## Next
Cycle 5 (productionization: STEP ingestion + frontend cost surface + observability) → then **FINAL HANDOFF** (DONE-PENDING-GATES): everything built, gates routed to the humans/3rd-parties who must close them.

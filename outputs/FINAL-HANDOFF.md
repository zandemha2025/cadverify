# CadVerify — FINAL HANDOFF (DONE-PENDING-GATES)

**Run:** 2026-06-28 → 2026-06-29 · 5 build cycles · ~3.0M agent tokens · every cycle audited + independently re-run by the orchestrator.
**Verdict:** All `[buildable]` Definition-of-Done items are met or honestly bounded. The only remaining items require humans / third parties. This document routes each one.

---

## What we set out to do
Turn CadVerify (a process-agnostic manufacturability engine with a *toy* cost model — hardcoded `cost_per_cm³ × volume`) into a product whose **decision-layer output (real cost, lead time, quantity economics, make-vs-buy) is credible to demanding manufacturing buyers** — positioned like the survivor **3D Spark** (fast, broad-process, glass-box, design-engineer-facing), not dead **CASTOR** (additive-first) and not heavyweight-opaque **aPriori**. That decision layer was the missing half: CadVerify had the engineering-check half; this build added the business-decision half.

## What got built (all verified by running it, not by reading agent notes)

| Cycle | Delivered | Independent verification |
|---|---|---|
| **1** | V0 decision layer `backend/src/costing/` — itemized, provenance-tagged should-cost + lead time + crossover + make-vs-buy; G1 refuses broken geometry | Ran CLI on real parts; broken MAF → `GEOMETRY_INVALID`; 17 tests |
| **2** | V1 hardening — fixed all 8 auditor weaknesses (decision coherence, AM nesting, min-charge floor, region split, tooling model, per-lot setup); **accuracy harness with MEASURED error bands** | Headline `make-now == low-qty reco` confirmed live; harness honestly flagged its own serial-AM miss; 36 tests |
| **3** | Residual fixes (AM lead-time 2–4yr → weeks; serial-AM bias into band, C2 FAIL→PASS) + **`POST /api/v1/validate/cost`** (auth, kill-switch, structured errors, no persistence, zero egress) | Lead-time 55–103d verified; endpoint 8/8 tests; 48 total |
| **4** | **Ground-truth labeling system** — 667-part licensed, provenance-tracked corpus + `/label` frontend tool (Three.js viewer) + routing-accuracy & k-NN similarity eval harness | 667 STL == manifest, `sha256(content)==filename`; **0 auto-labels** (circularity avoided); eval refuses metrics at 0/30 labels |
| **5** | **STEP ingestion** (gmsh → mesh → DFM+cost, real LGPL file end-to-end) + **frontend cost surface** (`/cost`) + observability/reliability hardening | gmsh 4.15.2; `eight_cyl.stp` → coherent decision; `npm run build` green; **500 backend tests pass / 5 env-gated skips** |

**Invariants holding end-to-end across all cycles:** every dollar traces to a driver with `MEASURED/USER/DEFAULT` provenance; `unit_cost == Σ(line_items)` enforced; broken geometry never produces a confident cost; the legacy toy model is never surfaced; zero network egress in the cost/serve path; CAD stays local (`data/` gitignored, no persistence).

## What is demoable TODAY
- **CLI:** `python -m src.costing.cli <part.stl|.step> --qty 50,5000` → full glass-box decision card.
- **API:** `POST /api/v1/validate/cost` (STL + STEP).
- **Frontend:** `/cost` decision surface + `/label` ground-truth labeler.
- **Demo packet:** `outputs/validation-packet.md` (5-beat script + honest weakness list + 10 questions for the Zoox contact).

---

## HONEST RESIDUALS (built but bounded — say these out loud)
1. **Absolute cost is ±~40–60%; the *decision* (crossover qty + make-vs-buy direction) is what V1 stands behind.** Measured bands: CNC/IM/powder-bed in band; serial-AM brought into band in C3. Real accuracy still needs ground truth (below).
2. **STEP is mesh-level, not B-rep.** gmsh tessellates STEP → DFM+cost works; **GD&T / PMI / AP242 tolerance extraction is BLOCKED** (needs cadquery/OCP, not installable in this env). IGES not implemented.
3. **The corpus leans additive** — openly-licensed injection-molded/cast/stamped meshes are essentially unavailable without gated datasets. Routing ground truth for non-additive families is thin until real parts are added.
4. **Routing-accuracy and cost-accuracy are not yet validated against reality** — that is a human/data gate, not a code gap.

---

## THE GATES — what's left, who closes it, and the artifact that's ready

| # | Gate | Who acts | Prepared artifact / what it needs |
|---|---|---|---|
| G1 | **Human expert validation — Zoox Head of Manufacturing demo** | You + the validator | `outputs/validation-packet.md` (coherent V1 demo). Run it on real parts; capture his answers (esp. CASTOR autopsy + willingness-to-pay). Sets the next direction. |
| G2 | **Human labeling — ≥30 real manufacturing-method labels** | You / a manufacturing person | `/label` tool is live over the 667-part corpus. After ≥30 labels: `python -m src.eval.run --build-features` then `python -m src.eval.run` → real routing-accuracy + confusion matrix. |
| G3 | **Cost-accuracy validation vs real quotes** | You + a few real shop/bureau quotes | Drop real quotes into the accuracy harness to convert "independent-band cross-check" into "measured error vs actual." Turns ±60% into a defended number. |
| G4 | **More non-additive corpus parts** (CNC/molded/stamped/cast) | You (or licensed-dataset access / Zoox parts) | Gatherer is reproducible (`python -m src.corpus.gather`); add sources. Needed for balanced routing ground truth. |
| G5 | **STEP B-rep / GD&T (AP242)** | Env with cadquery/OCP, or a deploy target with a wheel | Code degrades cleanly to 501 when absent; `step_mesher` covers mesh-level today. |
| G6 | **Security audit / SOC 2 / pen test** | Third party | Cost path has no CAD persistence + zero egress + structured logs with no CAD/secret leakage — a clean surface to audit. |
| G7 | **Export control / ITAR + Saudi data-residency** | Legal / compliance | Local-first / no-third-party-egress design supports this; needs formal classification. |
| G8 | **On-prem / VPC deployment acceptance; encryption-at-rest / tenant isolation** | Buyer IT/security | No CAD-at-rest in the cost path today; multi-tenant + at-rest encryption are deployment-time work per buyer. |
| G9 | **Procurement / MSA; cost-data licensing (if pursued); wedge & pricing go/no-go** | You / business dev | Positioning analysis in `outputs/strategy.md`; pricing is your call. |

**Immediate next move:** G1 (Zoox demo) and G2 (label ≥30 parts) — both have working artifacts right now and both produce the data that makes the next build cycle worth running.

---

## How to run everything
```bash
# cost decision on a real part (STL or STEP)
cd backend && CADVERIFY_PARTS_DIR=<parts> .venv/bin/python -W ignore -m src.costing.cli <part> --qty 50,5000

# labeling tool (frontend + gated backend)
LABELING_ENABLED=1 <serve backend>   # mounts /api/v1/corpus
cd frontend && npm run dev            # open /label  and  /cost

# routing-accuracy eval (after ≥30 human labels)
cd backend && .venv/bin/python -m src.eval.run --build-features && .venv/bin/python -m src.eval.run

# full test suite
cd backend && .venv/bin/python -W ignore -m pytest -q     # 500 passed / 5 env-gated skips
```

All code is in the working tree, **uncommitted** — review the diff (`backend/src/costing/`, `backend/src/eval/`, `backend/src/corpus/`, `backend/src/parsers/step_mesher.py`, `backend/src/api/`, `frontend/src/app/{cost,label}/`) before committing. `data/` (corpus + labels, 2.6 GB) is gitignored.

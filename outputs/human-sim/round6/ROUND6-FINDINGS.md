# Round-6 Human-Sim — Assembly Manufacturing Intelligence (AS1, commit c65dca3)

**Personas:** EPC design engineer (P1) + skeptical CFO (P5). Real signup, real STEP
upload of the AS1 assembly (18 solids), Playwright + vision on every step.

## Per-flow scores
| Flow | Score | Why |
|---|---|---|
| Signup / login | 4.5 | Completed; cosmetic hydration-mismatch + a 400 resource on /verify. |
| Assembly detection | 5 | 18 solids, 5 unique designs, not refused; honest header. |
| Part fidelity (3D stage) | 5 | Real tessellated shells in world positions; selected part highlighted, rest dimmed X-ray. |
| **Manufacturing intelligence** | **4.5** | Honesty framing excellent; inferred size is internally incoherent. **Does NOT clear 5.** |
| Single-part control (regression) | 5 | cube.step renders + full deterministic verdict; no regression. |

## Verdict: manufacturing-intelligence is 4.5, NOT 5.
**Blocker:** the Round-5 "lead with approximate size" feature prints an **≈M16 bolt
threading into an ≈M12 nut** in the *same* `NUT-BOLT-ASSEMBLY` joint. Physically
impossible; a sharp EPC engineer catches it instantly.

## Findings < 5 (ranked)
- **F1 — MEDIUM (blocker):** mating bolt/nut inferred with incompatible threads
  (≈M16 bolt vs ≈M12 nut, same joint). Root cause: `infer_fastener_size` computes
  each part independently, never reconciled against the mate. → mate reconciliation.
- **F2 — MEDIUM:** bolt over-sized vs its own geometry. bbox 30×15×37, vol 3.2 cm³ →
  volume-implied ø ≈ 10.5 mm → M10, but the rule snaps the head-skewed transverse to
  M16. → volume-sane estimator (min of bbox-transverse and volume-implied ø).
- **F3 — LOW:** nut DFM `best_process = Sheet Metal` (thin 20×20×3 bbox trips the
  sheet-metal heuristic). A hex nut is never sheet metal; it's a BUY/COTS part. →
  suppress the machined best-process claim on COTS parts.
- **F4 — LOW:** rod (flat prismatic bar 200×20×10) should-costs on CNC 5-Axis.
  Core routing smell, separate deferred task (touches every single-part flow).
- **F5 — LOW:** /verify hydration-mismatch console error + a 400 resource. Cosmetic.

## What the fix got right (why it's 4.5, not lower — the honesty work is strong)
BUY card leads with the size + green BUY pill + `~$0.75`/`~$0.20`; `DEFAULT`
provenance chip; verbatim "≈, NOT a verified thread spec, no grade implied"; the
misleading in-house machined figure is GONE ("MADE-IN-HOUSE · NOT MODELED");
recommendation reads BUY; identical designs get identical analysis; the plate is
material-coherent and glass-box (CNC 3-Axis, 6061-T6, MODEL provenance).

## Regression vs single-part control: none.

Screenshots in this directory. `05b-bolt-cots-card.png` + `06b-nut-cots-card.png`
are the proof of F1 (≈M16 vs ≈M12).

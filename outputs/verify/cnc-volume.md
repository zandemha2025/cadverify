# Verify — Item 2: CNC real volume/learning curve (cost audit S1)

**Verdict: CLOSED + PRODUCTION-WORTHY → MERGED to prod.**
Branch `feat/cnc-volume` (builder commit cc9de08). Wright cumulative-average learning curve on attended conversion cost (machine + post-labor) for subtractive+fabrication; DEFAULT `learning_rate=0.90`, `floor=0.25`, anchored at first production lot; numerical make-vs-buy crossover.

## The finding (closed)
CNC unit cost was volume-invariant ($46.10/$64.74 flat at 100/1k/100k). A flat variable cost pushed the make-vs-buy crossover to the wrong quantity.

## Evidence (independently reproduced)
- **Finding verifier (high conf):** OFF-switch reproduces the original flat behavior (machine+labor per-unit dead flat across qty); ON gives monotone decline, **100→10k drop ≈49%** (in the defensible 30–60% band), Σ(line_items)==unit_cost at every qty to ~1e-15, curve **anchored at first lot** (qty≤lot_size identical ON vs OFF). 18 costing tests pass.
- **Honesty verifier (high conf):** the drop is an **emergent** Wright consequence (machine AND labor both scale by exactly 0.9^log2(100)=0.4966 at 10k — not a hardcoded ~50%). `learning_curve` driver tagged `Provenance.DEFAULT` + `[assumption, not shop-validated]`; confidence keeps `validated=False` / `method=assumption-band` — never masquerades as measured. **Both off-switches** (`CADVERIFY_CNC_LEARNING=0`, `rate_overrides learning_rate=1.0`) recover the exact old flat cost. Family scoping correct (only subtractive+fabrication learn; formative does not; material never learns; setup unchanged).
- **Crossover (verified by orchestrator directly):** `_numerical_crossover` scans actual per-qty curves (geometric bracket + bisection). Known-answer synthetic: make=10 flat, tool=5+F/q → crossover **1000** (F=5000) and **2000** (F=10000) — finite, correctly ordered, **monotone in tooling fixed cost**. Returns None gracefully when tooling always/never wins. Real `estimate_decision` wiring confirmed (`unit_cost_fn` → `_numerical_crossover`); a thin plate correctly yields None (sheet_metal dominates, costs decline $4.68→$1.88).
- **Full-suite merge gate (backend/data present):** **561 passed, 7 skipped, 0 failed** (452s). The 3 "failures" the builder saw were a worktree env artifact (gitignored `backend/data/shop_profiles/` absent), resolved via symlink — confirmed 0 real failures.

## Flagged for the Zoox gate (not self-certified)
The **magnitude** of the volume curve (the 0.90 rate, the 30–60% envelope) is an assumption, not shop-validated — its correctness is a Zoox-gated question (real quotes → measured residual). The **direction** (machined cost drops with volume; crossover moves right with tooling cost) is manufacturing-correct and now behaves. Two small turned parts dip just below the (qty-flat) accuracy reference band at qty 1000 — a known residual in the fix's direction, honestly disclosed in the harness report.

Merged: feat/cnc-volume → dev → prod.

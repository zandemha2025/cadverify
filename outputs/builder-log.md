# CadVerify V0 Decision Layer — Builder Log

**Status:** DONE. Code written + RUN on real automotive parts; both md deliverables written with real captured output; 17/17 tests pass.
**Builder:** Builder agent · **Date:** 2026-06-28

## What was built
Self-contained package `backend/src/costing/` (10 modules) + CLI + 2 test files, exactly per `outputs/v0-spec.md` §1.2:
`provenance.py, rates.py, drivers.py, routing.py, cost_model.py, leadtime.py, decision.py, estimate.py, report.py, cli.py, __init__.py`
plus `backend/tests/test_costing_gates.py`, `backend/tests/test_costing_model.py`.

The layer is read-only over the engine (`AnalysisResult` + `mesh` + `features`); it never mutates the engine, the registry, or `result`, and never surfaces the legacy toy `estimated_cost_factor`. Every emitted number is a provenance-tagged (MEASURED / USER / DEFAULT) `Driver` with a non-empty `source`, and `unit_cost == Σ line_items` is asserted before any estimate is returned.

## Verified on real parts (venv python 3.9, trimesh)
- **ECU Firewall Mount** (66.79 cm³, 160×62×33, watertight): full decision card — 8 costed processes, SLS/PA12 reproduces the spec §6.4 worked example to the cent (material $4.45, machine $103.82, lead time 28–52 d). Crossover FDM↔injection-molding ≈ 583 units.
- **Throttle Body Adapter** (2.81 cm³, rotational): full decision card — `cnc_turning` correctly surfaces (rotational) and wins at low qty ($14.93/unit); injection molding wins at qty 10000 ($2.46/unit); crossover ≈ 387.
- **MAF Sensor Adapter** (vol=0, non-watertight): G1 gate fires — `GEOMETRY_INVALID`, zero estimates, no fabricated cost (the teardown's headline bug is dead).
- G1 across the set: 11 of 105 STL parts are refused (incl. the MAF adapter AND the Upper Intake Manifold Gasket the spec named); 94 are costed.

## One deviation from the literal spec (documented, honest — NOT a block)
**Spec §5.3 rule #1** ("DFM-feasible: engine `verdict != 'fail'`") would *exclude* injection molding / die casting on **every** real part here, because these STLs were modeled for 3D printing and so have **no mold draft** → the engine (correctly) emits an ERROR-level `INSUFFICIENT_DRAFT` and `verdict == 'fail'`. But the spec's own headline demo (§6.4), the make-vs-buy wedge (§8), and the **G4 acceptance test** all *require* injection molding to be costed and to produce the tooling crossover. The literal rule and the acceptance test are mutually exclusive against live engine behavior.

**Resolution (faithful to author intent + the HONESTY constraint):** by default the layer **costs** a DFM-fail process but **flags** it `dfm_ready=False` and prints the engine's actual blocker message (e.g. *"564 sidewall faces (96.9%) below 1.0° draft"*). The make-now recommendation only uses DFM-ready processes; the tooling/production path may reference the flagged molding option, explicitly labelled *"requires design-for-molding (add draft)."* Routing-sanity (no turning on a non-rotational bracket; no superalloy on a polymer part — gate G2) is enforced regardless. The literal spec §5.3 behavior is preserved as an opt-in: `EstimateOptions(strict_dfm=True)` / CLI `--strict-dfm` drops `verdict=='fail'` processes. No DFM verdict is ever faked; no number is fabricated.

## Tests
`pytest tests/test_costing_model.py tests/test_costing_gates.py` → **17 passed** (gates G1–G7 + model invariants). Gate tests read real parts via `CADVERIFY_PARTS_DIR` (skip cleanly if absent); model tests are procedural and always run.

---

[DFM-UX] BUILT dfm-scope-flags

[COST] BUILT cnc-volume

---

[SRE] BUILT engine-memory
[PLATFORM] BUILT cost-persist

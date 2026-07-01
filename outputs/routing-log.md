# Routing+Physics-Builder — work log

Status: **DONE** (not blocked). Deliverables: code changes (below) +
`outputs/routing-readme.md`. Buckets attacked: **2 (routing)**, **3 (cycle-time)**.

## Root causes found (measured, not assumed)
- `SHEET_METAL` was not in `COSTED_PROCESSES` → a flat panel could never get a $.
- `analysis/processes/checks.py::check_bends` used `dihedral < 90°`, but
  `ctx.dihedral_angles_rad` is the angle **between face normals** (0° = flat).
  So every flat facet pair tripped `SHARP_BEND` (ERROR) and `sheet_metal` hit
  `verdict=fail score=0.0` on **every** part. Verified before fix on
  Art2SideCover / TB_gasket / Ancel_Seal / ECU — all `fail (SHARP_BEND)`.
- DFM "best process" ranks by *absence* of violations → a 2 mm panel read as
  `wire_edm`/`binder_jetting` (noise). Routing was effectively a coin flip.

## Changes (files)
1. `analysis/processes/checks.py` — `check_bends` now flags knife-edge folds
   (normal divergence > 150°), not flat regions. Flat blanks + 90° bends pass.
2. `costing/drivers.py` — new MEASURED sheet drivers: `sheet_gauge_mm`,
   `planar_aspect`, `outline_perimeter_mm` (rim-area/gauge cut length),
   `bend_count` (distinct planar fold orientations), `sheet_like` predicate.
3. `costing/rates.py` — `FABRICATION` family, `SHEET_METAL` ∈ `COSTED_PROCESSES`,
   `process_family→"fabrication"`, BAND_PCT fabrication=35%, a full SHEET_METAL
   rate entry (cut_speed/ref_gauge/sec_per_bend/handling, all DEFAULT/overridable).
4. `costing/cost_model.py` — `_sheet_cycle` (cut÷speed + bends + handling),
   fabrication material branch (rectangular blank), family dispatch.
5. `costing/routing.py` — `select_sheet_material`, `_routing_sane(SHEET_METAL)`
   gated on `sheet_like`, sheet material wiring in `eligible_processes`, and
   `recommend_routing` (archetype classifier with surfaced reasoning).
6. `costing/decision.py` — `fabrication` added to MAKE_NOW_FAMILIES.
7. `costing/estimate.py` — compute + attach `routing` recommendation, add
   reconciliation note; `DecisionReport.routing` field.
8. `costing/report.py` — serialize `routing`; render `GEOMETRIC ROUTING →` block.

## Verified on real parts (polymer DEFAULT)
- Art2SideCover (2×120×280, 1.9mm): `mjf $26.12` → `sheet_panel → sheet_metal
  $5.46` (5052-Al, dfm=pass). Sheet cycle fully itemized.
- Ancel_Seal (1.4×81×171): `mjf $11.71` → `sheet_metal $4.94`.
- ECU firewall mount (32.6×62×160, 7.6mm): stays `mjf $44.13`, archetype
  `bulk_solid` (correctly NOT sheet — box, not panel).
- ThrottleBody FD3S: `cnc_turning $62.61`, archetype `rotational` (reasoning now
  surfaced). Parktronik/RingOuter (Al): `cnc_turning`.
- Routes to sheet metal across polymer/steel/aluminum classes (geometry-driven).

## Tests (all green — no regression)
- Fast procedural (test_costing_model, scoring_ties, analyzers, eval_harness,
  features, context, api): **53 passed, 1 skipped** (env boolean-ops skip, pre-existing).
- Rule packs / cost API / materials / registry / capability: **61 passed**.
- dedup / history: **15 passed**.
- NEW `tests/test_routing_sheet.py` (procedural regression guard): **4 passed**.
- Real-parts gates + accuracy (test_costing_gates, test_costing_accuracy):
  **26 passed (exit 0)** — G1–G7, make-vs-buy coherence, min-charge floor,
  powder-bed nesting, and the independent accuracy harness (≥80% in-band,
  all-processes ±60% bias bar) all hold. Sheet-metal estimates carry no
  independent reference, so the harness cleanly skips them (`ref_band → None`).
- Report JSON round-trips with the new `routing` field (cost-API path clean).

/**
 * Unit tests for the crossover scrub interpolation (frontend/src/lib/verify/scrub.ts).
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping. Proves the honesty contract of the interpolated scrub:
 *   (a) at a REAL computed point the value is the engine's own number (exact:true);
 *   (b) between two computed points it interpolates the two real points (exact:false,
 *       lo/hi name the bracket) and lands strictly between their unit costs;
 *   (c) outside the ladder it clamps to the nearest end point (clamped:true), never
 *       extrapolating a cost the engine never computed;
 *   (d) a process with no estimates yields unit:null — withheld, never faked.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { interpUnitCost } from "./scrub.ts";
import type { CostReport, CostEstimate } from "@/lib/api";

function est(process: string, quantity: number, unit_cost_usd: number): CostEstimate {
  return {
    process,
    material: "PP",
    quantity,
    unit_cost_usd,
    fixed_cost_usd: 0,
    variable_cost_usd: unit_cost_usd,
    est_error_band_pct: 40,
    dfm_ready: true,
    dfm_verdict: "pass",
    dfm_score: 90,
    dfm_blockers: [],
    line_items: {},
    drivers: [],
    lead_time: { low_days: 5, high_days: 10, mid_days: 7, components: {}, capacity: {} },
  };
}

function report(estimates: CostEstimate[]): CostReport {
  return {
    filename: "object.stl",
    status: "OK",
    reason: null,
    geometry: { volume_cm3: 4.63, surface_area_cm2: 30, bbox_mm: [21, 21, 21], watertight: true, face_count: 423 },
    material_class: "polymer",
    quantities: [1, 100, 1000, 2000, 5000, 10000],
    estimates,
    engine_feasibility: [],
    notes: [],
    assumptions: [],
    decision: null,
  };
}

// A realistic amortizing ladder for one make-now process (fixed/qty + variable).
const LADDER = report([
  est("mjf", 1, 47.68),
  est("mjf", 100, 10.79),
  est("mjf", 1000, 10.45),
  est("mjf", 2000, 10.43),
  est("mjf", 5000, 10.42),
  est("mjf", 10000, 10.41),
]);

test("exact at a computed point — returns the engine's own value", () => {
  const p = interpUnitCost(LADDER, "mjf", 1000);
  assert.equal(p.exact, true);
  assert.equal(p.unit, 10.45);
  assert.equal(p.lo, 1000);
  assert.equal(p.hi, 1000);
  assert.equal(p.clamped, false);
});

test("between two points — interpolates strictly between the two real unit costs", () => {
  const p = interpUnitCost(LADDER, "mjf", 300); // between 100 and 1000
  assert.equal(p.exact, false);
  assert.equal(p.clamped, false);
  assert.equal(p.lo, 100);
  assert.equal(p.hi, 1000);
  assert.ok(p.unit != null);
  // strictly inside [10.45, 10.79] (costs fall as qty rises)
  assert.ok((p.unit as number) < 10.79 && (p.unit as number) > 10.45);
});

test("below the ladder clamps to the smallest computed point — never extrapolated", () => {
  const p = interpUnitCost(LADDER, "mjf", 0.5);
  assert.equal(p.clamped, true);
  assert.equal(p.unit, 47.68);
  assert.equal(p.lo, 1);
});

test("above the ladder clamps to the largest computed point", () => {
  const p = interpUnitCost(LADDER, "mjf", 99999);
  assert.equal(p.clamped, true);
  assert.equal(p.unit, 10.41);
  assert.equal(p.hi, 10000);
});

test("a process the engine did not cost yields unit:null — withheld, never faked", () => {
  const p = interpUnitCost(LADDER, "injection_molding", 1000);
  assert.equal(p.unit, null);
  assert.equal(interpUnitCost(LADDER, null, 1000).unit, null);
});

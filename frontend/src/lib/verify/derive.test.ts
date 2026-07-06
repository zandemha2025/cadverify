/**
 * Unit tests for the Verify walk's pure derivations (frontend/src/lib/verify/derive.ts).
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping (see package.json "test"). No vitest/jest.
 *
 * Proves the honesty contract of the walk's cost math:
 *   (a) makeNow/tooling estimate selection follows the engine's decision.*_process
 *       and returns null (never a fake estimate) for an absent tooling route;
 *   (b) the log scrub maps fractions to quantities and snaps to REAL computed
 *       points only (nearestQty), never inventing an off-ladder quantity's cost;
 *   (c) driverViews carries the engine's provenance + verbatim source through and
 *       provenanceMix counts grounded vs guess honestly (MODEL/DEFAULT = hollow).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  makeNowEstimate,
  toolingEstimate,
  unitCostByQty,
  nearestQty,
  fractionToQty,
  qtyToFraction,
  driverViews,
  driverProvenance,
  provenanceMix,
} from "./derive.ts";
import type { CostReport, CostEstimate } from "@/lib/api";

function est(
  process: string,
  quantity: number,
  unit_cost_usd: number,
  drivers: CostEstimate["drivers"] = []
): CostEstimate {
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
    drivers,
    lead_time: { low_days: 5, high_days: 10, mid_days: 7, components: {}, capacity: {} },
  };
}

function report(estimates: CostEstimate[], decision: CostReport["decision"]): CostReport {
  return {
    filename: "object.stl",
    status: "OK",
    reason: null,
    geometry: {
      volume_cm3: 4.63,
      surface_area_cm2: 30,
      bbox_mm: [21.16, 21.43, 21.48],
      watertight: true,
      face_count: 423,
    },
    material_class: "polymer",
    quantities: [10, 1000, 10000],
    estimates,
    engine_feasibility: [],
    notes: [],
    assumptions: [],
    decision,
  };
}

test("makeNowEstimate follows decision.make_now_process and picks the stable high-qty read", () => {
  const r = report(
    [est("mjf", 10, 14.14), est("mjf", 10000, 6.45), est("injection_molding", 10000, 5.9)],
    {
      make_now_process: "mjf",
      make_now_material: "PP",
      tooling_process: "injection_molding",
      tooling_dfm_ready: true,
      crossover_qty: 1962,
      recommendation: {},
      if_redesigned: {},
      note: "",
    }
  );
  const mn = makeNowEstimate(r);
  assert.equal(mn?.process, "mjf");
  assert.equal(mn?.quantity, 10000); // largest-qty = fully amortized setup
  assert.equal(makeNowEstimate(r, 10)?.quantity, 10); // exact qty honored
});

test("toolingEstimate returns null when the engine declared no tooling route", () => {
  const r = report([est("mjf", 10, 14.14)], {
    make_now_process: "mjf",
    make_now_material: "PP",
    tooling_process: null,
    tooling_dfm_ready: false,
    crossover_qty: null,
    recommendation: {},
    if_redesigned: {},
    note: "",
  });
  assert.equal(toolingEstimate(r), null);
});

test("environment-excluded estimates are withheld from verify cost reads", () => {
  const invalid = {
    ...est("cnc_3axis", 1000, 11.5),
    material: "304 Stainless",
    environment_excluded: true,
    environment_exclusion_reason:
      "304 Stainless excluded: sour service requires NACE MR0175 qualification",
  };
  const valid = { ...est("cnc_3axis", 10, 21.5), material: "API 13Cr" };
  const toolInvalid = {
    ...est("investment_casting", 1000, 8.5),
    material: "304 Stainless",
    environment_excluded: true,
  };
  const r = report([invalid, valid, toolInvalid], {
    make_now_process: "cnc_3axis",
    make_now_material: "API 13Cr",
    tooling_process: "investment_casting",
    tooling_dfm_ready: true,
    crossover_qty: null,
    recommendation: {},
    if_redesigned: {},
    note: "",
  });

  assert.equal(makeNowEstimate(r)?.unit_cost_usd, 21.5);
  assert.equal(toolingEstimate(r), null);

  const costs = unitCostByQty(r, "cnc_3axis");
  assert.equal(costs.has(1000), false);
  assert.equal(costs.get(10), 21.5);
});

test("unitCostByQty maps only the engine's computed points for a process", () => {
  const r = report([est("mjf", 10, 14.14), est("mjf", 1000, 7.2), est("im", 1000, 6.1)], null);
  const m = unitCostByQty(r, "mjf");
  assert.equal(m.get(10), 14.14);
  assert.equal(m.get(1000), 7.2);
  assert.equal(m.has(1000) && m.get(1000) !== 6.1, true);
  assert.equal(unitCostByQty(r, null).size, 0);
});

test("nearestQty snaps to a real computed quantity — never an off-ladder guess", () => {
  assert.equal(nearestQty([1, 10, 100, 1000], 44), 10);
  assert.equal(nearestQty([1, 10, 100, 1000], 60), 100);
  assert.equal(nearestQty([], 500), 500);
});

test("log scrub maps fraction↔quantity monotonically over [1,10000]", () => {
  assert.equal(fractionToQty(0), 1);
  assert.equal(fractionToQty(1), 10000);
  assert.equal(fractionToQty(0.5), 100);
  assert.ok(Math.abs(qtyToFraction(100) - 0.5) < 1e-9);
  assert.equal(qtyToFraction(1), 0);
  assert.equal(qtyToFraction(10000), 1);
});

test("driverViews carries engine provenance + verbatim source; mix counts grounded honestly", () => {
  const e = est("mjf", 10, 14.14, [
    { name: "labor_cost", value: 6.39, unit: "usd", provenance: "SHOP", source: "0.082 hr × $52/hr", error_band_pct: 40 },
    { name: "material_cost", value: 0.04, unit: "usd", provenance: "MEASURED", source: "4.63 cm³ × 0.90 g/cm³", error_band_pct: null },
    { name: "parts_per_build", value: 223, unit: "count", provenance: "DEFAULT", source: "generic packing model", error_band_pct: null },
  ]);
  const views = driverViews(e);
  assert.equal(views[0].label, "Labor");
  assert.equal(views[0].source, "0.082 hr × $52/hr");
  assert.equal(views[0].provenance, "SHOP");
  assert.equal(views[2].provenance, "DEFAULT");

  const mix = provenanceMix(e);
  assert.equal(mix.total, 3);
  assert.equal(mix.shop, 1);
  assert.equal(mix.measured, 1);
  assert.equal(mix.default, 1);
  assert.equal(mix.groundedPct, 67); // 2 of 3 grounded
  assert.equal(provenanceMix(null).total, 0);
});

test("hours are MODEL: an ungrounded time driver reads ○ MODEL, geometry stays ● MEASURED", () => {
  // an hours-denominated driver the engine left DEFAULT → refined to MODEL (never grounded)
  assert.equal(
    driverProvenance({ name: "machine_time", value: 0.068, unit: "hr/part", provenance: "DEFAULT", source: "", error_band_pct: null }),
    "MODEL"
  );
  // a grounded time driver is NEVER downgraded to MODEL
  assert.equal(
    driverProvenance({ name: "labor_time", value: 0.082, unit: "hr", provenance: "SHOP", source: "", error_band_pct: null }),
    "SHOP"
  );
  // a non-time DEFAULT driver stays DEFAULT (only hours become MODEL)
  assert.equal(
    driverProvenance({ name: "parts_per_build", value: 223, unit: "count", provenance: "DEFAULT", source: "", error_band_pct: null }),
    "DEFAULT"
  );
  // measured geometry stays MEASURED
  assert.equal(
    driverProvenance({ name: "material_mass", value: 4.2, unit: "g", provenance: "MEASURED", source: "", error_band_pct: null }),
    "MEASURED"
  );
});

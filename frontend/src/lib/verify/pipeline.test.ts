/**
 * Unit tests for the pipeline overlay's lifecycle model (pipeline.ts).
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping (type-only imports are erased). No vitest/jest.
 *
 * Proves the honesty contract of the request-lifecycle overlay:
 *   (a) in flight → only `received` has landed; every downstream stage is pending
 *       with NO fabricated value;
 *   (b) a real result maps each stage to the ENGINE's value (geometry ● MEASURED,
 *       routing + confidence, the Σ make-now unit cost) and marks gates WITHHELD —
 *       never a fake pass — when no makeability block was returned;
 *   (c) the walk STOPS at a real failed gate (broken geometry, environment-excluded
 *       verdict); every stage past the stop reads "not computed", never faked.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { pipelineModelFrom } from "./pipeline.ts";
import type { VerifyResult, CostGeometryInvalid } from "./run";
import type { CostEstimate, CostReport, CostGeometry, ValidationResult } from "@/lib/api";
import type { VerificationBlock } from "./verification";

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

const GEOM: CostGeometry = {
  volume_cm3: 4.63,
  surface_area_cm2: 30,
  bbox_mm: [21.16, 21.16, 21.43],
  watertight: true,
  face_count: 423,
};

function report(over: Partial<CostReport> = {}): CostReport {
  return {
    filename: "object.stl",
    status: "OK",
    reason: null,
    geometry: GEOM,
    material_class: "polymer",
    quantities: [1, 100, 1000],
    estimates: [est("cnc_turning", 1, 22), est("cnc_turning", 1000, 14.14)],
    engine_feasibility: [],
    notes: [],
    assumptions: [],
    decision: {
      make_now_process: "cnc_turning",
      make_now_material: "AL",
      tooling_process: null,
      tooling_dfm_ready: false,
      crossover_qty: null,
      recommendation: {},
      if_redesigned: {},
      note: "",
    },
    ...over,
  };
}

function result(over: Partial<VerifyResult> = {}): VerifyResult {
  return {
    file: { name: "object.stl" } as File,
    validation: null,
    validationError: null,
    cost: null,
    costGeometryInvalid: null,
    costError: null,
    machines: [],
    machinesError: null,
    verification: null,
    quantities: [1, 100, 1000],
    env: { temp: false, sour: false, pressure: false },
    envDeclared: false,
    envCaptured: false,
    envError: null,
    ...over,
  };
}

test("in flight: only received has landed; downstream stages are pending with no value", () => {
  const m = pipelineModelFrom(null, true, "object.stl");
  assert.equal(m.computing, true);
  assert.equal(m.stopIndex, -1);
  assert.equal(m.stages.length, 5);
  assert.equal(m.stages[0].key, "received");
  assert.equal(m.stages[0].state, "done");
  for (const s of m.stages.slice(1)) assert.equal(s.state, "pending");
});

test("happy path: geometry ● MEASURED, routing, Σ make-now — gates WITHHELD when no block returned", () => {
  const r = result({
    cost: report(),
    validation: { best_process: "cnc_turning" } as unknown as ValidationResult,
  });
  const m = pipelineModelFrom(r, false, null);
  assert.equal(m.computing, false);
  assert.equal(m.stopIndex, -1);

  const measured = m.stages[1];
  assert.equal(measured.state, "done");
  assert.equal(measured.measured, true);
  assert.match(measured.detail, /21\.16 × 21\.16 × 21\.43 mm/);
  assert.match(measured.detail, /4\.63 cm³/);
  assert.match(measured.detail, /watertight true/);

  assert.equal(m.stages[2].state, "done"); // routed off best_process
  assert.match(m.stages[2].detail, /cnc_turning/);

  // No verification block → gates are WITHHELD (not a fabricated pass), walk continues.
  assert.equal(m.stages[3].state, "withheld");
  assert.match(m.stages[3].detail, /not evaluated/);

  // Σ = largest-qty make-now unit cost, not the qty-1 figure.
  assert.equal(m.stages[4].state, "done");
  assert.match(m.stages[4].detail, /Σ \$14\.14/);
});

test("broken geometry: measured is the failed gate; everything past it is not computed", () => {
  const invalid: CostGeometryInvalid = {
    message: "Non-watertight mesh — repair required.",
    geometry: { ...GEOM, watertight: false },
  };
  const r = result({ cost: null, costGeometryInvalid: invalid });
  const m = pipelineModelFrom(r, false, null);
  assert.equal(m.stopIndex, 1);
  assert.equal(m.stages[1].state, "blocked");
  assert.equal(m.stages[1].blocking, true);
  assert.match(m.stages[1].detail, /repair required/);
  for (const s of m.stages.slice(2)) {
    assert.equal(s.state, "pending");
    assert.match(s.detail, /not computed past the failed gate/);
  }
});

test("environment-excluded verdict: gates is the failed gate; the record is not computed", () => {
  const v: VerificationBlock = {
    verdict: "environment_excluded",
    env_exclusions: [
      {
        gate: "material_survival",
        axis: "PA12",
        need: null,
        have: null,
        human: "PA12 excluded by NACE MR0175 under sour service",
      },
    ],
  };
  const r = result({ cost: report(), verification: v });
  const m = pipelineModelFrom(r, false, null);
  assert.equal(m.stopIndex, 3);
  assert.equal(m.stages[3].state, "blocked");
  assert.match(m.stages[3].detail, /environment-excluded/);
  assert.match(m.stages[3].detail, /NACE MR0175/);
  assert.equal(m.stages[4].state, "pending");
  assert.match(m.stages[4].detail, /not computed past the failed gate/);
});

test("makeable_in_house verdict: gates clears, the record lands", () => {
  const v: VerificationBlock = { verdict: "makeable_in_house", best_machine: "Haas ST-10" };
  const r = result({ cost: report(), verification: v });
  const m = pipelineModelFrom(r, false, null);
  assert.equal(m.stopIndex, -1);
  assert.equal(m.stages[3].state, "done");
  assert.equal(m.stages[3].tone, "pass");
  assert.match(m.stages[3].detail, /Haas ST-10/);
  assert.match(m.stages[3].detail, /clears every gate/);
  assert.equal(m.stages[4].state, "done");
});

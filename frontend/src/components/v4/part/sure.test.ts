import test from "node:test";
import assert from "node:assert/strict";
import { buildMethods } from "./model.ts";
import { sureOf, type SureInput } from "./sure.ts";

type AnyObj = Record<string, unknown>;

function est(process: string, quantity: number, unit: number, extra: AnyObj = {}) {
  return {
    process,
    material: "PP",
    quantity,
    unit_cost_usd: unit,
    fixed_cost_usd: 0,
    variable_cost_usd: unit,
    est_error_band_pct: 50,
    confidence: { low_usd: unit * 0.5, high_usd: unit * 1.5, point_usd: unit, level: 0.8, method: "assumption-band", validated: false, n_samples: 0, half_width_pct: 50, basis: "", label: "" },
    dfm_ready: true,
    dfm_verdict: "pass",
    dfm_score: 0.9,
    dfm_blockers: [],
    line_items: {},
    drivers: [
      { name: "labor_cost", value: unit * 0.55, unit: "$", provenance: "DEFAULT", source: "0.5 hr × $35/hr", error_band_pct: 20 },
      { name: "machine_cost", value: unit * 0.3, unit: "$", provenance: "USER", source: "0.02 hr × $85/hr", error_band_pct: 50 },
      { name: "material_cost", value: unit * 0.15, unit: "$", provenance: "MEASURED", source: "3 cm³", error_band_pct: 5 },
    ],
    lead_time: { low_days: 5, high_days: 9, mid_days: 7, components: {}, capacity: {} },
    ...extra,
  };
}

function input(over: Partial<SureInput> = {}, costExtra: AnyObj = {}): SureInput {
  const validation = {
    filename: "block.iges",
    file_type: "iges",
    overall_verdict: "pass",
    best_process: "mjf",
    analysis_time_ms: 1000,
    geometry: { vertices: 10, faces: 100, volume_mm3: 2720, surface_area_mm2: 1432, bounding_box_mm: [20, 15, 10], is_watertight: true, is_manifold: true, center_of_mass: [0, 0, 0], units: "mm" },
    segments: [],
    universal_issues: [],
    process_scores: [{ process: "mjf", score: 0.9, verdict: "pass", recommended_material: "PP", recommended_machine: null, estimated_cost_factor: null, issues: [] }],
    priority_fixes: [],
  };
  const cost = {
    filename: "block.iges",
    status: "OK",
    reason: null,
    geometry: { volume_cm3: 2.72, surface_area_cm2: 14.32, bbox_mm: [20, 15, 10], watertight: true, face_count: 100 },
    material_class: "polymer",
    quantities: [10],
    estimates: [est("mjf", 10, 7.5, costExtra)],
    engine_feasibility: [],
    notes: [],
    assumptions: [],
    decision: null,
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const v = validation as any, c = cost as any;
  const methods = buildMethods({ validation: v, cost: c, machines: [] });
  return { validation: v, cost: c, machines: [], env: null, methods, q: 10, ...over };
}

test("Cost: the band, how many inputs are yours, and whether real jobs back it", () => {
  const s = sureOf("cost", input())!;
  assert.equal(s.line, "±50% · 2 of 3 inputs from your file or shop · not yet checked against real jobs");
  assert.deepEqual(s.items.map((x) => [x.kind, x.k]), [["typ", "Range"], ["file", "From your file"], ["yours", "From your shop or you"], ["typ", "Typical defaults"], ["typ", "Biggest line"], ["file", "Shape"]]);
  assert.match(s.items[0].v, /a stated assumption band, not yet checked against real jobs$/);
  assert.match(s.items[4].v, /55% of the price: a typical value$/);
  assert.deepEqual(s.next, { text: "Add your rates", to: "rates" }, "the biggest line is typical, so your rates would help most");
});

test("Cost checked against real jobs says so", () => {
  const s = sureOf("cost", input({}, { confidence: { low_usd: 6, high_usd: 9, point_usd: 7.5, level: 0.8, method: "measured-residual", validated: true, n_samples: 8, half_width_pct: 20, basis: "", label: "" } }))!;
  assert.equal(s.line, "±20% · 2 of 3 inputs from your file or shop · checked against real jobs");
  assert.equal(s.items[0].kind, "yours");
  assert.match(s.items[0].v, /checked against 8 of your real jobs$/);
});

test("Process: shape from the file, typical rules, default material, no conditions", () => {
  const s = sureOf("make", input())!;
  assert.equal(s.line, "Shape from your file · typical design rules · default material");
  assert.deepEqual(s.items.map((x) => x.kind), ["file", "typ", "typ", "typ"]);
  assert.deepEqual(s.next, { text: "Set where it’s used", to: "conditions" });
  const hot = sureOf("make", input({ env: { max_temp_c: 120 } as never }))!;
  assert.equal(hot.items.find((x) => x.k === "Conditions")!.kind, "yours");
  assert.equal(hot.next, null);
});

test("In-house with no machines says nothing is checked, and where to add one", () => {
  const s = sureOf("shop", input())!;
  assert.equal(s.line, "No machines yet · nothing checked in-house");
  assert.deepEqual(s.next, { text: "Add a machine", to: "machines" });
});

test("Nothing to say before anything is measured or priced", () => {
  assert.equal(sureOf("make", input({ validation: null, cost: null, methods: [] })), null);
  assert.equal(sureOf("cost", input({ cost: null, methods: [] })), null);
});

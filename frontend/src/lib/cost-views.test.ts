/**
 * Unit tests for the pure cost-views derivations (frontend/src/lib/cost-views.ts).
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping (see package.json "test"). No vitest/jest.
 *
 * This is the shared lens layer every role-aware workspace view (Decision /
 * Glass Box / Compare / Routing) binds to — it had ZERO tests before this file.
 *
 * Proves:
 *   (a) the override-key mapping (assumption + driver) is exactly the CLI's
 *       --set surface, and refuses anything outside that allowlist;
 *   (b) parseDriverRate reads the engine's OWN verbatim rate string back and
 *       returns null (never a fabricated number) when it can't parse one —
 *       the cost-views analog of the "—" not-fake-zero contract used
 *       elsewhere (see cost-decision.test.ts's formatUnitCostDelta);
 *   (c) fmtAssumptionValue formats every unit the engine speaks;
 *   (d) pickEstimate snaps to the nearest costed quantity and returns null
 *       (not a fake estimate) for an uncosted process;
 *   (e) parseCalibration never invents a shop name: null when nothing is
 *       calibrated, the real name when a note says so, and an honest
 *       "your shop profile" fallback only when SHOP-tagged rates exist
 *       without a note;
 *   (f) buildCompareRows / blockersByProcess transform real estimates only,
 *       sorted cheapest-at-high-volume first.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  assumptionOverrideKey,
  canOverrideAssumption,
  driverOverrideKey,
  canOverrideDriver,
  driverRateLabel,
  driverRateUnit,
  parseDriverRate,
  costedProcesses,
  costedQuantities,
  pickEstimate,
  makeNowStableEstimate,
  estimateHalfWidth,
  fmtAssumptionValue,
  parseCalibration,
  buildCompareRows,
  blockersByProcess,
} from "./cost-views.ts";
import type { CostReport, CostEstimate, CostAssumption, CostDriver, CostDecision } from "@/lib/api";

/* ---- fixture helpers -------------------------------------------- */

function leadTime(): CostEstimate["lead_time"] {
  return { low_days: 5, high_days: 10, mid_days: 7, components: {}, capacity: {} };
}

function est(over: Partial<CostEstimate> & Pick<CostEstimate, "process" | "quantity" | "unit_cost_usd">): CostEstimate {
  return {
    material: "aluminum-6061",
    fixed_cost_usd: 0,
    variable_cost_usd: 0,
    est_error_band_pct: 10,
    dfm_ready: true,
    dfm_verdict: "pass",
    dfm_score: 90,
    dfm_blockers: [],
    line_items: {},
    drivers: [],
    lead_time: leadTime(),
    ...over,
  };
}

function assumption(over: Partial<CostAssumption> & Pick<CostAssumption, "name">): CostAssumption {
  return { value: 0, unit: "", provenance: "DEFAULT", source: "", ...over };
}

function driver(over: Partial<CostDriver> & Pick<CostDriver, "name">): CostDriver {
  return { value: 0, unit: "", provenance: "DEFAULT", source: "", error_band_pct: null, ...over };
}

function report(over: Partial<CostReport>): CostReport {
  return {
    filename: "part.stl",
    status: "OK",
    reason: null,
    geometry: {
      volume_cm3: 10,
      surface_area_cm2: 60,
      bbox_mm: [50, 50, 20],
      watertight: true,
      face_count: 1000,
    },
    material_class: "aluminum",
    quantities: [],
    estimates: [],
    engine_feasibility: [],
    notes: [],
    assumptions: [],
    decision: null,
    ...over,
  };
}

/* ---- (a) override-key mapping ------------------------------------ */

test("assumptionOverrideKey maps rate-card keys 1:1 and rejects the rest", () => {
  for (const k of ["labor_rate", "margin", "overhead", "utilization", "stock_allowance", "daily_machine_hours"]) {
    assert.equal(assumptionOverrideKey(k), k);
  }
  assert.equal(assumptionOverrideKey("n_cavities"), null, "cavities routes elsewhere, not the rate card");
  assert.equal(assumptionOverrideKey("complexity"), null);
  assert.equal(assumptionOverrideKey("region_us"), null);
});

test("canOverrideAssumption allows rate keys and n_cavities only", () => {
  assert.equal(canOverrideAssumption("labor_rate"), true);
  assert.equal(canOverrideAssumption("n_cavities"), true);
  assert.equal(canOverrideAssumption("material_class"), false);
  assert.equal(canOverrideAssumption("region_us"), false);
});

test("driverOverrideKey maps each driver to the underlying RATE it actually re-costs", () => {
  assert.equal(driverOverrideKey("machine_cost", "cnc_milling", "aluminum"), "machine_rate.CNC_MILLING");
  assert.equal(driverOverrideKey("labor_cost", "cnc_milling", "aluminum"), "labor_rate");
  assert.equal(driverOverrideKey("setup_cost", "cnc_milling", "aluminum"), "labor_rate");
  assert.equal(driverOverrideKey("material_cost", "cnc_milling", "aluminum"), "material_price.@aluminum");
  assert.equal(driverOverrideKey("unknown_driver", "cnc_milling", "aluminum"), null);
});

test("canOverrideDriver allows exactly the four editable driver names", () => {
  for (const d of ["machine_cost", "labor_cost", "setup_cost", "material_cost"]) {
    assert.equal(canOverrideDriver(d), true);
  }
  assert.equal(canOverrideDriver("overhead_cost"), false);
});

test("driverRateLabel/driverRateUnit describe the rate a driver edit sets", () => {
  assert.equal(driverRateLabel("machine_cost"), "machine rate");
  assert.equal(driverRateLabel("labor_cost"), "labor rate");
  assert.equal(driverRateLabel("setup_cost"), "labor rate");
  assert.equal(driverRateLabel("material_cost"), "material price");
  assert.equal(driverRateLabel("unknown"), "rate");

  assert.equal(driverRateUnit("material_cost"), "$/kg");
  assert.equal(driverRateUnit("machine_cost"), "$/hr");
  assert.equal(driverRateUnit("labor_cost"), "$/hr");
});

/* ---- (b) parseDriverRate: read the engine's own string, never fabricate */

test("parseDriverRate reads the rate verbatim out of the engine's source string", () => {
  const machineDriver = driver({ name: "machine_cost", source: "0.8 hr × $30/hr" });
  assert.equal(parseDriverRate(machineDriver), 30);

  const materialDriver = driver({ name: "material_cost", source: "0.42 kg × $7.5/kg" });
  assert.equal(parseDriverRate(materialDriver), 7.5);

  const laborDriver = driver({ name: "labor_cost", source: "1.2 hr × $52/hr" });
  assert.equal(parseDriverRate(laborDriver), 52);
});

test("parseDriverRate returns null (never a guessed rate) when the source can't be parsed", () => {
  const noRate = driver({ name: "machine_cost", source: "flat fee, no rate breakdown" });
  assert.equal(parseDriverRate(noRate), null);

  // wrong unit for the driver kind (material_cost looks for /kg, source only has /hr)
  const wrongUnit = driver({ name: "material_cost", source: "0.42 kg × $7.5/hr" });
  assert.equal(parseDriverRate(wrongUnit), null);
});

/* ---- (c) fmtAssumptionValue: every unit the engine speaks --------- */

test("fmtAssumptionValue formats each assumption unit the way the engine speaks it", () => {
  assert.equal(fmtAssumptionValue({ value: 52, unit: "$/hr" }), "$52/hr");
  assert.equal(fmtAssumptionValue({ value: 1500, unit: "$" }), "$1500");
  assert.equal(fmtAssumptionValue({ value: 1.1, unit: "×" }), "1.1×");
  assert.equal(fmtAssumptionValue({ value: 0.8, unit: "frac" }), "0.8");
  assert.equal(fmtAssumptionValue({ value: 0.8, unit: "" }), "0.8");
  assert.equal(fmtAssumptionValue({ value: 3, unit: "mm" }), "3 mm");
});

/* ---- (d) pickEstimate: nearest-quantity snap, null for unknown ---- */

test("pickEstimate snaps to the costed quantity nearest the requested one", () => {
  const r = report({
    estimates: [
      est({ process: "cnc_milling", quantity: 50, unit_cost_usd: 22 }),
      est({ process: "cnc_milling", quantity: 5000, unit_cost_usd: 2.2 }),
    ],
  });
  assert.equal(pickEstimate(r, "cnc_milling", 40)?.quantity, 50, "closer to 50 than 5000");
  assert.equal(pickEstimate(r, "cnc_milling", 4000)?.quantity, 5000, "closer to 5000 than 50");
  assert.equal(pickEstimate(r, "cnc_milling")?.quantity, 50, "no qty => first costed estimate");
});

test("pickEstimate breaks an exact-midpoint tie toward the first-seen estimate", () => {
  const r = report({
    estimates: [
      est({ process: "cnc_milling", quantity: 100, unit_cost_usd: 10 }),
      est({ process: "cnc_milling", quantity: 200, unit_cost_usd: 6 }),
    ],
  });
  // 150 is equidistant from 100 and 200; reduce()'s strict `<` keeps `best`
  // (the first element) on a tie rather than overwriting it.
  assert.equal(pickEstimate(r, "cnc_milling", 150)?.quantity, 100);
});

function decision(over: Partial<CostDecision> = {}): CostDecision {
  return {
    make_now_process: "cnc_milling",
    make_now_material: "aluminum-6061",
    tooling_process: null,
    tooling_dfm_ready: false,
    crossover_qty: null,
    recommendation: {},
    if_redesigned: {},
    note: "",
    ...over,
  };
}

test("makeNowStableEstimate anchors the drivers to the amortized headline qty, not the first (F5)", () => {
  // The reported mismatch: the Inspector drivers reconciled to qty 100 ($8.72)
  // while the should-cost headline reads the amortized qty 10,000 ($8.68).
  const r = report({
    decision: decision({ make_now_process: "cnc_milling" }),
    estimates: [
      est({ process: "cnc_milling", quantity: 100, unit_cost_usd: 8.72 }),
      est({ process: "cnc_milling", quantity: 10000, unit_cost_usd: 8.68 }),
    ],
  });
  // pickEstimate(no qty) returned the FIRST (smallest) — the bug we replaced.
  assert.equal(pickEstimate(r, "cnc_milling")?.quantity, 100, "guards the old bug");
  // makeNowStableEstimate anchors to the LARGEST costed qty (setup amortized).
  const e = makeNowStableEstimate(r);
  assert.equal(e?.quantity, 10000, "drivers now read the headline's amortized qty");
  assert.equal(e?.unit_cost_usd, 8.68, "reconciles to the headline's unit cost");
});

test("makeNowStableEstimate ignores other processes and is order-independent", () => {
  const r = report({
    decision: decision({ make_now_process: "cnc_milling" }),
    estimates: [
      est({ process: "cnc_milling", quantity: 10000, unit_cost_usd: 8.68 }),
      est({ process: "cnc_milling", quantity: 100, unit_cost_usd: 8.72 }),
      est({ process: "die_casting", quantity: 100000, unit_cost_usd: 2.1 }),
    ],
  });
  assert.equal(makeNowStableEstimate(r)?.quantity, 10000, "largest cnc qty even when listed first");
});

test("makeNowStableEstimate returns null (never fabricates) with no decision or no make-now estimate", () => {
  assert.equal(
    makeNowStableEstimate(report({ estimates: [est({ process: "cnc_milling", quantity: 100, unit_cost_usd: 8.72 })] })),
    null,
    "no decision => null"
  );
  assert.equal(
    makeNowStableEstimate(
      report({
        decision: decision({ make_now_process: "cnc_milling" }),
        estimates: [est({ process: "die_casting", quantity: 100, unit_cost_usd: 2.1 })],
      })
    ),
    null,
    "no estimate for the make-now route => null"
  );
});

test("pickEstimate returns null (never a fabricated estimate) for an uncosted process", () => {
  const r = report({ estimates: [est({ process: "cnc_milling", quantity: 50, unit_cost_usd: 22 })] });
  assert.equal(pickEstimate(r, "die_casting", 50), null);
  assert.equal(pickEstimate(r, "die_casting"), null);
});

/* ---- estimateHalfWidth: prefer confidence, then error band, then 0 - */

test("estimateHalfWidth prefers the confidence band over the legacy error band", () => {
  const e = est({
    process: "cnc_milling",
    quantity: 50,
    unit_cost_usd: 10,
    est_error_band_pct: 25,
    confidence: {
      low_usd: 8,
      high_usd: 12,
      point_usd: 10,
      level: 0.8,
      method: "assumption-band",
      validated: false,
      n_samples: 0,
      half_width_pct: 14.7,
      basis: "assumption",
      label: "assumption-based, not yet validated",
    },
  });
  assert.equal(estimateHalfWidth(e), 15, "rounds the confidence half-width, not the legacy band");
});

test("estimateHalfWidth falls back to the legacy error band, then 0, when confidence is absent", () => {
  const withBand = est({ process: "p", quantity: 1, unit_cost_usd: 1, est_error_band_pct: 12.4 });
  assert.equal(estimateHalfWidth(withBand), 12);

  const noBandEstimate: CostEstimate = { ...withBand, est_error_band_pct: undefined as unknown as number };
  assert.equal(estimateHalfWidth(noBandEstimate), 0);
});

/* ---- (e) parseCalibration: never invent a shop name --------------- */

test("parseCalibration reads shopName/source straight off the 'calibrated to shop' note", () => {
  const r = report({
    notes: ["This report was calibrated to shop 'Acme Precision'. Source: shop_profile.json"],
    assumptions: [
      assumption({ name: "labor_rate", value: 48, unit: "$/hr", provenance: "SHOP", source: "shop_profile.json" }),
      assumption({ name: "margin", value: 1.15, unit: "×", provenance: "DEFAULT", source: "generic default" }),
    ],
  });
  const view = parseCalibration(r);
  assert.equal(view.shopName, "Acme Precision");
  assert.equal(view.source, "shop_profile.json");
  assert.equal(view.shopRates.length, 1);
  assert.equal(view.shopRates[0].display, "$48/hr");
  assert.equal(view.defaultRates.length, 1);
  assert.equal(view.defaultRates[0].display, "1.15×");
});

test("parseCalibration reads shopName null (not fabricated) when nothing is calibrated", () => {
  const r = report({
    notes: [],
    assumptions: [assumption({ name: "labor_rate", value: 40, unit: "$/hr", provenance: "DEFAULT" })],
  });
  const view = parseCalibration(r);
  assert.equal(view.shopName, null, "no fabricated shop name when every rate is generic");
  assert.equal(view.shopRates.length, 0);
  assert.equal(view.defaultRates.length, 1);
});

test("parseCalibration falls back to an honest 'your shop profile' label when rates are SHOP-tagged but there's no note", () => {
  const r = report({
    notes: [],
    assumptions: [assumption({ name: "labor_rate", value: 48, unit: "$/hr", provenance: "SHOP" })],
  });
  const view = parseCalibration(r);
  assert.equal(view.shopName, "your shop profile", "still honestly flagged as calibrated, just unnamed");
});

/* ---- (f) buildCompareRows / blockersByProcess ---------------------- */

test("buildCompareRows builds one row per costed process, sorted cheapest-at-high-volume first", () => {
  const r = report({
    estimates: [
      est({ process: "cnc_milling", quantity: 50, unit_cost_usd: 42.5, dfm_ready: true }),
      est({ process: "cnc_milling", quantity: 5000, unit_cost_usd: 12, dfm_ready: true }),
      est({ process: "injection_molding", quantity: 50, unit_cost_usd: 400, dfm_ready: false, dfm_blockers: ["needs draft angle"] }),
      est({ process: "injection_molding", quantity: 5000, unit_cost_usd: 3.1, dfm_ready: false }),
    ],
  });
  const rows = buildCompareRows(r, 50, 5000);
  assert.equal(rows.length, 2);
  // injection_molding (3.1 at high volume) beats cnc_milling (12) => sorted first
  assert.equal(rows[0].process, "injection_molding");
  assert.equal(rows[0].b.unitCost, 3.1);
  assert.equal(rows[0].b.redesign, true, "not dfm-ready => flagged as an if-redesigned figure");
  assert.equal(rows[1].process, "cnc_milling");
  assert.equal(rows[1].a.unitCost, 42.5);
  assert.equal(rows[1].a.redesign, false);
});

test("costedProcesses/costedQuantities dedup in first-seen / ascending order respectively", () => {
  const r = report({
    estimates: [
      est({ process: "cnc_milling", quantity: 5000, unit_cost_usd: 12 }),
      est({ process: "injection_molding", quantity: 50, unit_cost_usd: 400 }),
      est({ process: "cnc_milling", quantity: 50, unit_cost_usd: 42.5 }),
    ],
  });
  assert.deepEqual(costedProcesses(r), ["cnc_milling", "injection_molding"]);
  assert.deepEqual(costedQuantities(r), [50, 5000]);
});

test("blockersByProcess only reports processes with a real dfm_blockers entry", () => {
  const r = report({
    estimates: [
      est({ process: "cnc_milling", quantity: 50, unit_cost_usd: 42.5, dfm_blockers: [] }),
      est({
        process: "injection_molding",
        quantity: 50,
        unit_cost_usd: 400,
        dfm_blockers: ["needs draft angle", "wall too thin"],
      }),
    ],
  });
  const blockers = blockersByProcess(r);
  assert.equal(Object.keys(blockers).length, 1, "clean process is absent, not blank");
  assert.equal(blockers.injection_molding, "needs draft angle", "first blocker, verbatim");
  assert.equal(blockers.cnc_milling, undefined);
});

/**
 * Unit tests for the pure make-vs-buy breakeven derivation (frontend/src/lib/breakeven.ts).
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping (see package.json "test"). No vitest/jest.
 *
 * This is the shared derivation layer under every cost surface (Decision hero,
 * breakeven chart, quantity slider) — it had ZERO tests before this file.
 *
 * Proves:
 *   (a) posToQty/qtyToPos are inverse log-maps and round-trip;
 *   (b) recommendAt flips at the numeric crossover between two curves, and
 *       prefers the cheapest DFM-READY curve over a cheaper-but-not-ready one
 *       (falling back to the raw cheapest only when NOTHING is ready);
 *   (c) the two-point curve fit passes exactly through the report's own
 *       reported unit costs (no invented figures) — the "glass box" promise;
 *   (d) the single-point fallback prefers the engine's fixed/variable split
 *       when it reproduces the reported unit cost, and falls back to a flat
 *       line (never a guessed split) when it doesn't;
 *   (e) deriveBreakeven's qtyMax/qtyMin bounds and its null-on-no-decision guard.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  unitCostAt,
  deriveBreakeven,
  recommendAt,
  posToQty,
  qtyToPos,
  sampleQuantities,
} from "./breakeven.ts";
import type { Breakeven, ProcessCurve } from "./breakeven.ts";
import type { CostReport, CostEstimate, CostDecision } from "@/lib/api";

/* ---- fixture helpers -------------------------------------------- */

function geometry(): CostReport["geometry"] {
  return {
    volume_cm3: 10,
    surface_area_cm2: 60,
    bbox_mm: [50, 50, 20],
    watertight: true,
    face_count: 1000,
  };
}

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

function report(over: Partial<CostReport>): CostReport {
  return {
    filename: "part.stl",
    status: "OK",
    reason: null,
    geometry: geometry(),
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

/* ---- (a) posToQty / qtyToPos round-trip -------------------------- */

test("posToQty maps slider endpoints to qtyMin/qtyMax exactly", () => {
  const b: Breakeven = {
    curves: [],
    qtyMin: 1,
    qtyMax: 10000,
    crossoverQty: null,
    makeNowProcess: "cnc_milling",
    toolingProcess: null,
  };
  assert.equal(posToQty(b, 0), 1);
  assert.equal(posToQty(b, 1), 10000);
});

test("qtyToPos is the inverse of posToQty at the midpoint (log-space)", () => {
  const b: Breakeven = {
    curves: [],
    qtyMin: 1,
    qtyMax: 10000,
    crossoverQty: null,
    makeNowProcess: "cnc_milling",
    toolingProcess: null,
  };
  // qtyMin=1, qtyMax=10000 are both powers of ten, so the log-midpoint is
  // exactly 100 and the round-trip is exact (up to fp epsilon).
  const midQty = posToQty(b, 0.5);
  assert.equal(midQty, 100);
  const pos = qtyToPos(b, midQty);
  assert.ok(Math.abs(pos - 0.5) < 1e-9, `expected ~0.5, got ${pos}`);
});

test("qtyToPos clamps quantities outside [qtyMin, qtyMax]", () => {
  const b: Breakeven = {
    curves: [],
    qtyMin: 10,
    qtyMax: 1000,
    crossoverQty: null,
    makeNowProcess: "cnc_milling",
    toolingProcess: null,
  };
  assert.equal(qtyToPos(b, 1), 0, "below qtyMin clamps to pos 0");
  assert.equal(qtyToPos(b, 1_000_000), 1, "above qtyMax clamps to pos 1");
});

test("posToQty/qtyToPos round-trip across a sweep of positions", () => {
  const b: Breakeven = {
    curves: [],
    qtyMin: 1,
    qtyMax: 50000,
    crossoverQty: null,
    makeNowProcess: "cnc_milling",
    toolingProcess: null,
  };
  for (const pos of [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]) {
    const qty = posToQty(b, pos);
    const back = qtyToPos(b, qty);
    // posToQty rounds to an integer qty, so the round-trip is approximate,
    // not exact, except at the extremes.
    assert.ok(Math.abs(back - pos) < 0.01, `pos=${pos} -> qty=${qty} -> back=${back}`);
  }
});

/* ---- unitCostAt --------------------------------------------------- */

test("unitCostAt is fixedAmort/q + variablePerUnit, and Infinity for q<=0", () => {
  const c: ProcessCurve = {
    process: "cnc_milling",
    material: "aluminum-6061",
    fixedAmort: 1000,
    variablePerUnit: 2,
    dfmReady: true,
    leadLow: null,
    leadHigh: null,
    points: [],
  };
  assert.equal(unitCostAt(c, 50), 22); // 1000/50 + 2
  assert.equal(unitCostAt(c, 5000), 2.2); // 1000/5000 + 2
  assert.equal(unitCostAt(c, 0), Infinity, "never divide by zero into a fake number");
  assert.equal(unitCostAt(c, -5), Infinity);
});

/* ---- (c) two-point curve fit passes exactly through the reported ---
      unit costs (the "glass box" no-invented-figures promise)        */

test("deriveBreakeven's two-point fit reproduces the report's own unit costs exactly", () => {
  const r = report({
    quantities: [50, 5000],
    decision: decision({ crossover_qty: null }),
    estimates: [
      // fixedAmort=1000, variablePerUnit=2 => unit(50)=22, unit(5000)=2.2
      est({ process: "cnc_milling", quantity: 50, unit_cost_usd: 22 }),
      est({ process: "cnc_milling", quantity: 5000, unit_cost_usd: 2.2 }),
    ],
  });
  const b = deriveBreakeven(r)!;
  assert.ok(b, "decision present => non-null breakeven");
  const curve = b.curves.find((c) => c.process === "cnc_milling")!;
  assert.ok(Math.abs(curve.fixedAmort - 1000) < 1e-6);
  assert.ok(Math.abs(curve.variablePerUnit - 2) < 1e-6);
  // the fitted curve must reproduce the EXACT reported numbers at both points
  assert.equal(unitCostAt(curve, 50), 22);
  assert.equal(unitCostAt(curve, 5000), 2.2);
  assert.deepEqual(curve.points, [
    { qty: 50, unit: 22 },
    { qty: 5000, unit: 2.2 },
  ]);
});

/* ---- (d) single-point fallback: prefer the engine's split when it ---
      reproduces the reported number; else a flat line, never a guess  */

test("single costed quantity: uses the engine's fixed/variable split when it reproduces unit_cost_usd", () => {
  const r = report({
    quantities: [200],
    decision: decision(),
    estimates: [
      // fixed=500, variable=3 => pred = 500/200+3 = 5.5, matches unit_cost_usd exactly
      est({
        process: "mjf",
        quantity: 200,
        unit_cost_usd: 5.5,
        fixed_cost_usd: 500,
        variable_cost_usd: 3,
      }),
    ],
  });
  const b = deriveBreakeven(r)!;
  const curve = b.curves.find((c) => c.process === "mjf")!;
  assert.equal(curve.fixedAmort, 500);
  assert.equal(curve.variablePerUnit, 3);
});

test("single costed quantity: falls back to a flat line (no invented split) when fixed/variable don't reproduce it", () => {
  const r = report({
    quantities: [100],
    decision: decision(),
    estimates: [
      // fixed=500, variable=1 => pred = 500/100+1 = 6, far from unit_cost_usd=10
      est({
        process: "mjf",
        quantity: 100,
        unit_cost_usd: 10,
        fixed_cost_usd: 500,
        variable_cost_usd: 1,
      }),
    ],
  });
  const b = deriveBreakeven(r)!;
  const curve = b.curves.find((c) => c.process === "mjf")!;
  assert.equal(curve.fixedAmort, 0, "no invented fixed amortization");
  assert.equal(curve.variablePerUnit, 10, "flat line at the one real reported number");
  assert.equal(unitCostAt(curve, 1), 10);
  assert.equal(unitCostAt(curve, 999999), 10);
});

test("single costed quantity with no fixed/variable split at all falls back to a flat line", () => {
  const r = report({
    quantities: [40],
    decision: decision(),
    estimates: [est({ process: "die_casting", quantity: 40, unit_cost_usd: 7.25 })],
  });
  const b = deriveBreakeven(r)!;
  const curve = b.curves.find((c) => c.process === "die_casting")!;
  assert.equal(curve.fixedAmort, 0);
  assert.equal(curve.variablePerUnit, 7.25);
});

/* ---- (b) recommendAt: flips at the crossover, prefers DFM-ready ----- */

/** Two curves crossing exactly at q=1000: A flat $5/unit, B = 4000/q + 1. */
function crossingBreakeven(opts: { aReady: boolean; bReady: boolean }): Breakeven {
  const a: ProcessCurve = {
    process: "A",
    material: "aluminum-6061",
    fixedAmort: 0,
    variablePerUnit: 5,
    dfmReady: opts.aReady,
    leadLow: null,
    leadHigh: null,
    points: [],
  };
  const b: ProcessCurve = {
    process: "B",
    material: "nylon-pa12",
    fixedAmort: 4000,
    variablePerUnit: 1,
    dfmReady: opts.bReady,
    leadLow: null,
    leadHigh: null,
    points: [],
  };
  return {
    curves: [a, b],
    qtyMin: 1,
    qtyMax: 10000,
    crossoverQty: 1000,
    makeNowProcess: "A",
    toolingProcess: "B",
  };
}

test("recommendAt picks the cheaper curve below and above the crossover", () => {
  const be = crossingBreakeven({ aReady: true, bReady: true });
  const below = recommendAt(be, 500)!;
  assert.equal(below.curve.process, "A", "below crossover A ($9) beats B ($9)"); // A=5, B=4000/500+1=9
  assert.equal(below.unitCost, 5);

  const above = recommendAt(be, 2000)!;
  assert.equal(above.curve.process, "B", "above crossover B is cheaper"); // A=5, B=4000/2000+1=3
  assert.equal(above.unitCost, 3);
});

test("recommendAt at the exact crossover: both curves tie, stable order picks the first", () => {
  const be = crossingBreakeven({ aReady: true, bReady: true });
  const at = recommendAt(be, 1000)!;
  assert.equal(unitCostAt(be.curves[0], 1000), unitCostAt(be.curves[1], 1000), "curves truly tie at 1000");
  assert.equal(at.unitCost, 5);
  assert.equal(at.curve.process, "A", "stable sort keeps first-seen order on an exact tie");
});

test("recommendAt prefers the cheapest DFM-READY curve over a cheaper-but-not-ready one", () => {
  // Below the crossover A is cheaper (5 < 9) but NOT dfm-ready; B is ready.
  const be = crossingBreakeven({ aReady: false, bReady: true });
  const rec = recommendAt(be, 500)!;
  assert.equal(rec.curve.process, "B", "B is the cheapest READY process, even though A is cheaper overall");
  assert.equal(rec.dfmReady, true);
  assert.equal(rec.unitCost, 9); // 4000/500 + 1
});

test("recommendAt falls back to the raw cheapest when NOTHING is DFM-ready", () => {
  const be = crossingBreakeven({ aReady: false, bReady: false });
  const rec = recommendAt(be, 500)!;
  assert.equal(rec.curve.process, "A", "no ready process => fall back to cheapest overall");
  assert.equal(rec.dfmReady, false);
});

test("recommendAt returns null when there are no curves", () => {
  const be: Breakeven = {
    curves: [],
    qtyMin: 1,
    qtyMax: 10000,
    crossoverQty: null,
    makeNowProcess: "",
    toolingProcess: null,
  };
  assert.equal(recommendAt(be, 500), null);
});

/* ---- (e) deriveBreakeven bounds + null guard ----------------------- */

test("deriveBreakeven returns null when the report has no decision (pre-cost / GEOMETRY_INVALID)", () => {
  const r = report({ decision: null, estimates: [est({ process: "cnc_milling", quantity: 50, unit_cost_usd: 10 })] });
  assert.equal(deriveBreakeven(r), null);
});

test("qtyMax is at least 10000 and grows with 2x the authoritative crossover", () => {
  const base = report({
    quantities: [50, 5000],
    decision: decision({ crossover_qty: 1200 }),
    estimates: [
      est({ process: "cnc_milling", quantity: 50, unit_cost_usd: 22 }),
      est({ process: "cnc_milling", quantity: 5000, unit_cost_usd: 2.2 }),
    ],
  });
  const b = deriveBreakeven(base)!;
  assert.equal(b.qtyMin, 1);
  assert.equal(b.qtyMax, 10000, "crossover*2=2400 and maxCosted=5000 are both < the 10000 floor");
  assert.equal(b.crossoverQty, 1200, "authoritative engine crossover, not re-derived from the curves");

  const bigCrossover = report({
    ...base,
    decision: decision({ crossover_qty: 8000 }),
  });
  const b2 = deriveBreakeven(bigCrossover)!;
  assert.equal(b2.qtyMax, 16000, "crossover*2 (16000) beats the 10000 floor and maxCosted");
});

test("deriveBreakeven carries makeNowProcess/toolingProcess straight from the decision", () => {
  const r = report({
    quantities: [50],
    decision: decision({ make_now_process: "cnc_milling", tooling_process: "injection_molding" }),
    estimates: [est({ process: "cnc_milling", quantity: 50, unit_cost_usd: 10 })],
  });
  const b = deriveBreakeven(r)!;
  assert.equal(b.makeNowProcess, "cnc_milling");
  assert.equal(b.toolingProcess, "injection_molding");
});

/* ---- sampleQuantities: log-spaced, deduped, in range ---------------- */

test("sampleQuantities returns deduped, ascending, in-range samples spanning qtyMin..qtyMax", () => {
  const b: Breakeven = {
    curves: [],
    qtyMin: 1,
    qtyMax: 10000,
    crossoverQty: null,
    makeNowProcess: "",
    toolingProcess: null,
  };
  const samples = sampleQuantities(b, 20);
  assert.ok(samples.length > 0 && samples.length <= 20);
  assert.equal(samples[0], 1, "first sample is qtyMin");
  assert.equal(samples[samples.length - 1], 10000, "last sample is qtyMax");
  for (let i = 1; i < samples.length; i++) {
    assert.ok(samples[i] > samples[i - 1], "strictly ascending after Set-dedup");
  }
  assert.equal(new Set(samples).size, samples.length, "no duplicates");
});

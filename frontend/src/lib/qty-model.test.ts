import test from "node:test";
import assert from "node:assert/strict";
import { lotAverageFactor, modelAt, onceAndEach, unitCostAt, type CostQtyModel } from "./qty-model.ts";

// The cost engineer's pocket block (steel, 3-axis, v0 rates) as the engine stores it with
// the record priced at 100; the engine's own prices at each quantity beside it.
const POCKET: CostQtyModel = {
  v: 1,
  once_usd: 113.75, // setup 0.75 h + programming 2 h + first article 0.5 h, × $35
  per_part_usd: 1.306914, // material 0.5222 + tools and coolant 0.7847
  machine_usd: 15.693375, // 0.209245 h × $75
  learning_usd: 18.55, // labor 0.5 h + in-process inspection 0.03 h, × $35
  learning: { rate: 0.9, first_lot: 100, floor: 0.25 },
  per_plate: [],
  order_min_usd: 90,
  specs: [],
};
const ENGINE: [number, number][] = [
  [1, 149.3003],
  [25, 40.1003],
  [100, 36.6878],
  [250, 35.1562],
  [1000, 32.1966],
  [2500, 30.3237],
  [10000, 27.8412],
];

test("her 25: the model's own price, not the straight line between 1 and 100 (ce-06)", () => {
  // 0.52 + 15.69 + 17.50 + 0.78 + 26.25/25 + 70/25 + (0.5/25 + 0.03) × 35 = $40.10; the line read $55.98.
  assert.equal(modelAt(POCKET, 25).toFixed(2), "40.10");
});

test("the model matches the engine at every quantity she priced or asked for (within 2%: the same number)", () => {
  for (const [q, want] of ENGINE) {
    const got = unitCostAt({ qty_model: POCKET }, q)!;
    assert.ok(Math.abs(got - want) < 0.0005, `${q}: ${got} vs ${want}`);
    assert.ok(Math.abs(got - want) <= 0.02 * want);
  }
});

test("lot average: her 0.81 at 1,000 and 0.584 at 10,000; nothing inside the first lot", () => {
  assert.equal(lotAverageFactor(0.9, 100, 0.25, 1000).toFixed(3), "0.813");
  assert.equal(lotAverageFactor(0.9, 100, 0.25, 10000).toFixed(3), "0.584");
  assert.equal(lotAverageFactor(0.9, 100, 0.25, 100), 1);
  assert.equal(lotAverageFactor(1, 100, 0.25, 10000), 1);
});

test("no model on the record: no number", () => {
  assert.equal(unitCostAt({}, 25), null);
  assert.equal(unitCostAt({ qty_model: { ...POCKET, v: 2 } }, 25), null);
  assert.equal(unitCostAt({ qty_model: POCKET }, 0), null);
});

test("per-plate setups, order minimums, finishes and calibration", () => {
  const m: CostQtyModel = {
    v: 1, once_usd: 0, per_part_usd: 2, machine_usd: 3, learning_usd: 0, learning: null,
    per_plate: [{ lot_usd: 20, parts: 10 }], order_min_usd: 100,
    specs: [{ min_usd: 125, per_part_usd: 0.5 }, { once_usd: 210, per_part_usd: 0 }],
  };
  // q 5: core 2 + 3 + 20/5 = 9 → order minimum 100/5 = 20; anodize max(125, 2.5)/5 = 25; report 210/5 = 42
  assert.equal(modelAt(m, 5), 20 + 25 + 42);
  // q 1000: core 5 + 20 × 100 / 1000 = 7; anodize max(125, 500)/1000 = 0.5; report 0.21
  assert.ok(Math.abs(modelAt(m, 1000) - (7 + 0.5 + 0.21)) < 1e-9);
  // calibrated: machine × 1.2, then × 0.9
  assert.ok(Math.abs(unitCostAt({ qty_model: m, calibration: { hours_factor: 1.2, cost_factor: 0.9 } }, 1000)! - (7.71 + 0.6) * 0.9) < 1e-9);
  assert.deepEqual(onceAndEach(m, 1000).once, 210);
});

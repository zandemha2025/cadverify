import assert from "node:assert/strict";
import test from "node:test";
import { calculateMakeBuy } from "./make-buy-calculator.ts";

const example = { quantity: 500, makeFixed: 2000, makeVariable: 12, buyFixed: 200, buyVariable: 18 };
test("worked example reconciles totals and the crossover", () => {
  const result = calculateMakeBuy(example);
  assert.deepEqual(result, { makeTotal: 8000, buyTotal: 9200, makeUnit: 16, buyUnit: 18.4, savings: 1200, cheaper: "make", crossover: 300, crossoverType: "positive" });
  assert.equal(calculateMakeBuy({ ...example, quantity: 300 }).cheaper, "equal");
  assert.equal(calculateMakeBuy({ ...example, quantity: 100 }).cheaper, "buy");
});
test("handles equal rates, identical routes and a reversed crossover", () => {
  assert.equal(calculateMakeBuy({ ...example, buyVariable: 12 }).crossoverType, "none");
  assert.equal(calculateMakeBuy({ ...example, buyVariable: 12, buyFixed: 2000 }).crossoverType, "all");
  const reversed = calculateMakeBuy({ ...example, makeFixed: 200, buyFixed: 2000, makeVariable: 18, buyVariable: 12 });
  assert.equal(reversed.crossover, 300);
  assert.equal(reversed.cheaper, "buy");
});
test("zero and negative crossover quantities are not positive production crossovers", () => {
  assert.equal(calculateMakeBuy({ ...example, makeFixed: 200 }).crossoverType, "none");
  assert.equal(calculateMakeBuy({ ...example, makeFixed: 0 }).crossoverType, "none");
  assert.equal(calculateMakeBuy({ quantity: 1, makeFixed: 0, buyFixed: 0, makeVariable: 0, buyVariable: 0 }).cheaper, "equal");
});
test("rejects nonfinite, negative, fractional quantities and impractically large inputs", () => {
  for (const quantity of [0, -1, 0.5, NaN, Infinity, 1e10]) assert.throws(() => calculateMakeBuy({ ...example, quantity }));
  for (const key of ["makeFixed", "makeVariable", "buyFixed", "buyVariable"] as const) {
    for (const value of [-1, NaN, Infinity, 1e10]) assert.throws(() => calculateMakeBuy({ ...example, [key]: value }));
  }
});

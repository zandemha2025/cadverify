import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const source = readFileSync(new URL("./SavedCostDecisionView.tsx", import.meta.url), "utf8");
test("cost stamp is gated by dfm readiness and preserves confidence honesty", () => {
  assert.match(source, /headEstimate\?\.dfm_ready/);
  assert.match(source, /Manufacturable by/);
  assert.match(source, /unit_cost_usd\.toFixed\(2\)/);
  assert.match(source, /confidence\?\.validated/);
  assert.match(source, /Manufacturability\/cost stamp withheld/);
});

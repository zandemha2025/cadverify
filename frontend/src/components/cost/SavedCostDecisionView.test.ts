import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const source = readFileSync(new URL("./SavedCostDecisionView.tsx", import.meta.url), "utf8");
test("cost stamp is gated by dfm readiness and preserves confidence honesty", () => {
  assert.match(source, /routeDfmOutcome\(headEstimate\?\.dfm_verdict, headEstimate\)/);
  assert.match(source, /Estimated cost by/);
  assert.match(source, /unit_cost_usd\.toFixed\(2\)/);
  assert.match(source, /confidence\?\.validated/);
  assert.match(source, /Cost stamp withheld/);
});

import { test } from "node:test";
import assert from "node:assert/strict";

const { runningRateLine, runningRateWhy } = await import("./running-rate.ts");

test("the running rate is explained where it shows: what you typed, the share left out, and why (buyer-03)", () => {
  assert.equal(runningRateLine(87, null), "In-house prices use $56.55/h: $87.00/h you set, less a typical 35% that pays for the machine you already own. Buying outside uses a shop's full rate.");
  assert.equal(runningRateLine(87, 20), "In-house prices use $69.60/h: $87.00/h you set, less 20% that pays for the machine you already own. Buying outside uses a shop's full rate.");
  assert.equal(runningRateLine(null, 35), null);
  assert.equal(runningRateWhy(79, 0.35, true), "$79.00/h you set, less 35% that pays for the machine you already own");
});

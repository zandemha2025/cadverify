import test from "node:test";
import assert from "node:assert/strict";
import { expectedLine } from "./check-timing.ts";

const t = (over = {}) => ({ validate_s: 25, cost_s: 50, validate_samples: 3, cost_samples: 3, basis: "org" as const, running: 1, running_org: 1, ...over });

test("the card says how long checks take here, not a fixed 30 s (me-21)", () => {
  // 25 s of process checks + 50 s of pricing = 75 s.
  assert.equal(expectedLine(t(), 5000, true), "Your recent checks took about 75 s");
  assert.equal(expectedLine(t({ basis: "server" }), 5000, true), "Checks here take about 75 s lately");
  assert.equal(expectedLine(t({ validate_s: 40, cost_s: 60 }), 5000, true), "Your recent checks took about 1.5 min");
});

test("a busy server says so, and a slow check says it is slower than usual", () => {
  // Yours is one of the 4 running: 3 others.
  assert.equal(expectedLine(t({ running: 4 }), 5000, true), "Your recent checks took about 75 s · 3 other checks running on the server now");
  assert.equal(expectedLine(t(), 101000, true), "Taking longer than usual: 101 s so far (usually about 75 s)");
});

test("nothing measured yet: the time so far, never a promise; done: the time it took", () => {
  assert.equal(expectedLine(t({ validate_s: null, cost_s: null, basis: null }), 12000, true), "12 s so far");
  assert.equal(expectedLine(null, 3000, true), "3 s so far");
  assert.equal(expectedLine(t(), 70500, false), "71 s");
});

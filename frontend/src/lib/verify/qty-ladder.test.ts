import test from "node:test";
import assert from "node:assert/strict";
import { QTY_LADDER, quantityLadderFor, quantityLadderForAnnual } from "./qty-ladder.ts";

test("a declared annual volume is an exact point; the ladder keeps six points and its anchors", () => {
  assert.deepEqual(quantityLadderForAnnual(null), QTY_LADDER);
  assert.deepEqual(quantityLadderForAnnual(5000), QTY_LADDER, "already on the ladder");
  assert.deepEqual(quantityLadderForAnnual(500), [1, 100, 500, 2000, 5000, 10000], "500 is nearest 1,000 on the log scale");
  assert.deepEqual(quantityLadderForAnnual(50000), [1, 100, 1000, 2000, 10000, 50000]);
  assert.deepEqual(quantityLadderForAnnual(2.5), QTY_LADDER, "not a whole number");
});

test("the quantity carried from the cost breakdown is priced exactly, beside a declared annual volume", () => {
  assert.deepEqual(quantityLadderFor([null, 50]), [1, 50, 1000, 2000, 5000, 10000]);
  assert.deepEqual(quantityLadderFor([500, 50]), [1, 50, 500, 2000, 5000, 10000], "both are exact points");
  assert.deepEqual(quantityLadderFor([500, 500]), [1, 100, 500, 2000, 5000, 10000], "the same quantity once");
  assert.deepEqual(quantityLadderFor([null, 10000]), QTY_LADDER);
  assert.deepEqual(quantityLadderFor([null, 0]), QTY_LADDER);
  assert.deepEqual(quantityLadderFor([null, 20_000_000]), QTY_LADDER, "over the engine's limit");
  for (const q of [quantityLadderFor([3, 7]), quantityLadderFor([150000, 250000])]) assert.equal(q.length, 6);
});

import assert from "node:assert/strict";
import test from "node:test";

import {
  COST_DISPOSITIONS,
  costDispositionLabel,
  isCostDisposition,
} from "./cost-disposition.ts";

test("four-way disposition keys and labels stay exact", () => {
  assert.deepEqual(COST_DISPOSITIONS, [
    { key: "inhouse", label: "Make in-house" },
    { key: "outside", label: "Make outside" },
    { key: "acquire", label: "Acquire capability" },
    { key: "redesign", label: "Redesign" },
  ]);
});

test("labels and guards reject unsupported persisted values", () => {
  assert.equal(costDispositionLabel("outside"), "Make outside");
  assert.equal(costDispositionLabel(null), null);
  assert.equal(isCostDisposition("redesign"), true);
  assert.equal(isCostDisposition("maybe"), false);
});

import assert from "node:assert/strict";
import test from "node:test";

import {
  COST_DISPOSITION_NOTE_MAX_LENGTH,
  COST_DISPOSITIONS,
  costDispositionLabel,
  isCostDisposition,
  inhouseDispositionError,
  costDispositionBasisLabel,
} from "./cost-disposition.ts";
import type { CostReport, CostEstimate } from "./api";

test("four-way disposition keys and labels stay exact", () => {
  assert.equal(COST_DISPOSITION_NOTE_MAX_LENGTH, 1000);
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

test("sourcing eligibility follows the selected route, never an aggregate owned-machine pass", () => {
  const estimate = { process: "mjf", material: "PA12", quantity: 100, dfm_ready: true, dfm_verdict: "pass", dfm_blockers: [] } as unknown as CostEstimate;
  const report = { verification: { verdict: "makeable_in_house", per_route: {
    fdm: { verdict: "makeable_in_house" }, mjf: { verdict: "makeable_outsource_only" },
  } } } as unknown as CostReport;
  assert.match(inhouseDispositionError(report, estimate)!, /Owned-machine fit/);
  assert.equal(inhouseDispositionError(report, { ...estimate, process: "fdm" }), null);
  assert.match(inhouseDispositionError(report, { ...estimate, process: "fdm", dfm_ready: false })!, /Route DFM/);
  assert.match(inhouseDispositionError(null, estimate)!, /Owned-machine fit/);
  assert.match(inhouseDispositionError(report, null)!, /computed quantity/);
  assert.equal(costDispositionBasisLabel(estimate), "MJF (HP) · PA12 · qty 100");
  assert.equal(costDispositionBasisLabel(null), "Process and quantity were not recorded.");
});

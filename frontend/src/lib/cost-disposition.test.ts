import assert from "node:assert/strict";
import test from "node:test";

import {
  COST_DISPOSITION_NOTE_MAX_LENGTH,
  COST_DISPOSITIONS,
  costDispositionLabel,
  isCostDisposition,
  inhouseDispositionError,
  costDispositionBasisLabel,
  isBuyOutcome,
} from "./cost-disposition.ts";
import type { CostReport, CostEstimate } from "./api";

test("disposition keys and labels stay exact", () => {
  assert.equal(COST_DISPOSITION_NOTE_MAX_LENGTH, 1000);
  assert.deepEqual(COST_DISPOSITIONS, [
    { key: "inhouse", label: "Make in-house" },
    { key: "outside", label: "Make outside" },
    { key: "acquire", label: "Acquire capability" },
    { key: "redesign", label: "Redesign" },
    { key: "supplier", label: "Keep buying from our supplier" },
  ]);
});

test("keep buying from our supplier is a buy outcome with no route of ScaleCAD's", () => {
  assert.equal(costDispositionLabel("supplier"), "Keep buying from our supplier");
  assert.equal(isBuyOutcome("supplier"), true);
  assert.equal(isBuyOutcome("outside"), true);
  assert.equal(isBuyOutcome("inhouse"), false);
  const basis = { supplier: true, quantity: 800, usd_each: 89.82, price_source: "parts_list" } as never;
  assert.equal(costDispositionBasisLabel(basis), "From your supplier · $89.82 each · qty 800");
  assert.equal(costDispositionBasisLabel({ supplier: true, quantity: null, usd_each: null } as never), "From your supplier · no price entered");
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

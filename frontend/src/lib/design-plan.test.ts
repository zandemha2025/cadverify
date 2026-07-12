import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_DESIGN_FORM,
  buildDesignPlan,
  validateDesignForm,
} from "./design-plan.ts";

test("plate form becomes a four-hole allowlisted plan", () => {
  const plan = buildDesignPlan(DEFAULT_DESIGN_FORM);
  assert.equal(plan.kind, "plate");
  if (plan.kind !== "plate") throw new Error("wrong plan kind");
  assert.equal(plan.holes.length, 4);
  assert.deepEqual(plan.holes[0], { x_mm: -30, y_mm: -15, diameter_mm: 6 });
});

test("unsafe edge margin is explained before submission", () => {
  const error = validateDesignForm({
    ...DEFAULT_DESIGN_FORM,
    holeDiameter: 10,
    holeInset: 5,
  });
  assert.match(error ?? "", /at least 1 mm/);
});

test("bracket form emits no executable or free-form operation", () => {
  const plan = buildDesignPlan({ ...DEFAULT_DESIGN_FORM, kind: "bracket" });
  assert.deepEqual(Object.keys(plan).sort(), [
    "depth_mm",
    "height_mm",
    "kind",
    "thickness_mm",
    "width_mm",
  ]);
});

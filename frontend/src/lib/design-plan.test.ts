import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_DESIGN_FORM,
  buildDesignPlan,
  formFromPlan,
  resolveViewedRevisionNo,
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

test("interpreted hole inset is rounded for a human-readable form value", () => {
  const form = formFromPlan(
    {
      kind: "plate",
      width_mm: 120,
      depth_mm: 70,
      thickness_mm: 8,
      holes: [
        { x_mm: -51.6, y_mm: -26.6, diameter_mm: 10 },
        { x_mm: 51.6, y_mm: -26.6, diameter_mm: 10 },
        { x_mm: 51.6, y_mm: 26.6, diameter_mm: 10 },
        { x_mm: -51.6, y_mm: 26.6, diameter_mm: 10 },
      ],
    },
    "Plate 120 × 70 × 8 mm",
  );

  assert.equal(form.holeInset, 8.4);
});

test("switching designs resets a shared revision number to the new current revision", () => {
  const revisions = [{ number: 2 }, { number: 1 }];

  assert.equal(resolveViewedRevisionNo(1, revisions, 2, true), 2);
  assert.equal(resolveViewedRevisionNo(1, revisions, 2, false), 1);
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

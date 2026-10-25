import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_DESIGN_FORM,
  buildDesignPlan,
  designRevisionRefreshKey,
  draftAngleOf,
  supportsDraft,
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

test("revision history refreshes only for a real selected-design state change", () => {
  const generating = {
    id: "01DESIGN",
    current_revision: 2,
    status: "generating" as const,
  };

  assert.equal(
    designRevisionRefreshKey({ ...generating }),
    designRevisionRefreshKey({ ...generating }),
  );
  assert.notEqual(
    designRevisionRefreshKey(generating),
    designRevisionRefreshKey({ ...generating, status: "ready" }),
  );
  assert.notEqual(
    designRevisionRefreshKey(generating),
    designRevisionRefreshKey({ ...generating, current_revision: 3 }),
  );
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

const ENCLOSURE = { ...DEFAULT_DESIGN_FORM, kind: "enclosure" as const, width: 120, depth: 80, height: 40, wallThickness: 1 };

test("a zero draft sends today's plan; a draft is sent only for the plate and the enclosure", () => {
  assert.deepEqual(buildDesignPlan(ENCLOSURE), { kind: "enclosure", width_mm: 120, depth_mm: 80, height_mm: 40, wall_thickness_mm: 1 });
  assert.deepEqual(buildDesignPlan({ ...ENCLOSURE, draftAngle: 1.5 }), { kind: "enclosure", width_mm: 120, depth_mm: 80, height_mm: 40, wall_thickness_mm: 1, draft_angle_deg: 1.5 });
  const plate = buildDesignPlan({ ...DEFAULT_DESIGN_FORM, draftAngle: 2 });
  assert.equal(plate.kind === "plate" && plate.draft_angle_deg, 2);
  assert.ok(!("draft_angle_deg" in buildDesignPlan({ ...DEFAULT_DESIGN_FORM, kind: "bracket", draftAngle: 2 })));
});

test("a saved plan without a draft reads as 0, and a drafted one round-trips", () => {
  const legacy = { kind: "enclosure" as const, width_mm: 120, depth_mm: 80, height_mm: 40, wall_thickness_mm: 1 };
  assert.equal(formFromPlan(legacy, "Box").draftAngle, 0);
  assert.equal(draftAngleOf(legacy), 0);
  const drafted = { ...legacy, draft_angle_deg: 1.5 };
  assert.equal(formFromPlan(drafted, "Box").draftAngle, 1.5);
  assert.deepEqual(buildDesignPlan(formFromPlan(drafted, "Box")), drafted);
  assert.equal(draftAngleOf({ kind: "bracket", width_mm: 70, depth_mm: 35, height_mm: 55, thickness_mm: 5 }), null);
  assert.deepEqual([supportsDraft("plate"), supportsDraft("enclosure"), supportsDraft("bracket")], [true, true, false]);
});

test("drafted geometry is checked where it is tightest, like the server", () => {
  assert.equal(validateDesignForm({ ...ENCLOSURE, draftAngle: 1.5 }), null);
  const tall = { ...ENCLOSURE, width: 40, depth: 30, height: 200, wallThickness: 2 };
  assert.equal(validateDesignForm({ ...tall, draftAngle: 2 }), null);
  assert.match(validateDesignForm({ ...tall, draftAngle: 10 }) ?? "", /no room inside at the base/);
  assert.match(validateDesignForm({ ...DEFAULT_DESIGN_FORM, width: 20, depth: 20, thickness: 100, fourCornerHoles: false, draftAngle: 10 }) ?? "", /top face/);
  // 80 × 50 × 6 plate, 6 mm holes at a 4.5 mm inset: fine straight, too close to the edge at 10°.
  const corner = { ...DEFAULT_DESIGN_FORM, holeInset: 4.5 };
  assert.equal(validateDesignForm(corner), null);
  assert.match(validateDesignForm({ ...corner, draftAngle: 10 }) ?? "", /drafted top face/);
  assert.equal(validateDesignForm({ ...ENCLOSURE, draftAngle: 11 }), "Draft must be 0 to 10°.");
});

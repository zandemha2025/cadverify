import test from "node:test";
import assert from "node:assert/strict";
import { factLine, factRows, holeGroups, machineFacts, machineQuestion, pricedSetup, turnedSteps, turningPlan } from "./at-machine.ts";

const f = (kind: string, radius: number | null, depth: number | null, centroid: [number, number, number]) => ({ kind, radius, depth, centroid, area: 1, confidence: 0.99, face_count: 10 });

// me-16: stepped-shaft.step as the check measured it (cylinder bosses along file Z).
const SHAFT = [
  f("flat", null, null, [0, 0, 0]),
  f("cylinder_boss", 15, 20, [0, 0, 9.998]),
  f("cylinder_boss", 8, 30, [0, 0, 35.081]),
  f("cylinder_boss", 5, 10, [0, 0, 54.957]),
];
// pocket-block.step: two Ø4 holes 20 deep.
const POCKET = [f("flat", null, null, [30, 20, 0]), f("cylinder_hole", 2, 20, [5, 5, 10]), f("cylinder_hole", 2, 20, [55, 35, 10])];

const TURNING = {
  process: "cnc_turning",
  quantity: 25,
  drivers: [
    { name: "material_cost", value: 0.46, unit: "$", provenance: "DEFAULT", source: "bounding cylinder Ø30.00 × 60.00 mm × 1.10 stock allowance = 46.65 cm³ × Mild Steel density 7.85 g/cm³ = 0.3662 kg" },
    { name: "setup_cost", value: 0.96, unit: "$", provenance: "SHOP", source: "setup 0.5hr × $48/hr once for the order ÷ 25 × region-labor ×1" },
    { name: "inspection_cost", value: 1.97, unit: "$", provenance: "SHOP", source: "first-article 0.4hr × 1 setup(s) ÷ 25 + in-process 0.025hr/part" },
  ],
} as never;

test("a turned part's steps, end to end, from the measured cylinders (me-16)", () => {
  assert.deepEqual(turnedSteps(SHAFT as never), [{ dia: 30, len: 20 }, { dia: 16, len: 30 }, { dia: 10, len: 10 }]);
  // Read from the big end even when the file has it at the other end.
  const flipped = SHAFT.map((x) => ({ ...x, centroid: [0, 0, 60 - x.centroid[2]] as [number, number, number] }));
  assert.deepEqual(turnedSteps(flipped as never).map((s) => s.dia), [30, 16, 10]);
  // Bosses that don't line up on one axis aren't a turned part's steps.
  assert.deepEqual(turnedSteps([f("cylinder_boss", 5, 10, [0, 0, 0]), f("cylinder_boss", 5, 10, [40, 30, 0])] as never), []);
});

test("setups for the shaft: everything from the free end, then flip to face the parted end", () => {
  const plan = turningPlan([{ dia: 30, len: 20 }, { dia: 16, len: 30 }, { dia: 10, len: 10 }])!;
  assert.equal(plan.setups, 2);
  assert.equal(plan.ops[0], "OP10: hold the Ø30 mm stock in the chuck; face, turn Ø16 mm × 30 mm, then Ø10 mm × 10 mm from the free end; part off at 60 mm");
  assert.equal(plan.ops[1], "OP20: flip, grip a turned diameter (soft jaws); face the parted end to the 60 mm length");
  // A collar in the middle: each side in its own setup.
  const collar = turningPlan([{ dia: 10, len: 10 }, { dia: 30, len: 5 }, { dia: 16, len: 20 }])!;
  assert.deepEqual(collar.ops, ["OP10: turn one side up to the Ø30 mm collar: Ø16 mm × 20 mm", "OP20: flip, grip the turned side; turn the other: Ø10 mm × 10 mm"]);
});

test("holes are grouped by size; the price's own setup and stock are read from its lines", () => {
  assert.deepEqual(holeGroups(POCKET as never), [{ n: 2, dia: 4, depth: 20 }]);
  assert.deepEqual(pricedSetup(TURNING), { setupHours: 0.5, setups: 1, stock: "bounding cylinder Ø30.00 × 60.00 mm × 1.10 stock allowance" });
});

test("the facts an operator reads at the lathe, and the questions that ask for them", () => {
  const facts = machineFacts({ features: SHAFT as never, size: [30, 30, 60], rotational: true, estimate: TURNING, machine: "Haas ST-20, in-house", tolerance: null });
  const rows = factRows(facts);
  assert.deepEqual(rows.find((r) => r.k === "Steps")?.v, "Ø30 mm × 20 mm · Ø16 mm × 30 mm · Ø10 mm × 10 mm");
  assert.equal(rows.find((r) => r.k === "Setups: 2")?.v.startsWith("OP10"), true);
  assert.equal(rows.find((r) => r.k === "The price assumes")?.v, "1 setup, 0.5 h to set up, from bounding cylinder Ø30.00 × 60.00 mm × 1.10 stock allowance");
  assert.equal(rows.find((r) => r.k === "Tightest tolerance")?.v, "Not declared. Tighter callouts are on the print.");
  assert.equal(factLine(facts), "Ø30 × 20 mm, Ø16 × 30 mm, Ø10 × 10 mm · 2 setups · Haas ST-20, in-house");
  // A milled block: no steps, no plan, said so.
  const block = factRows(machineFacts({ features: POCKET as never, size: [60, 40, 20], rotational: false, estimate: null, machine: null, tolerance: "ISO 2768-m (medium)" }));
  assert.equal(block.find((r) => r.k === "Setups")?.v, "Not planned: ScaleCAD plans setups for turned parts only.");
  assert.equal(block.find((r) => r.k === "Holes")?.v, "2 × Ø4 mm × 20 mm deep");
  assert.equal(block.find((r) => r.k === "Tightest tolerance")?.v, "General ISO 2768-m (medium) (declared on Specs)");
  assert.equal(machineQuestion("How many setups on the lathe, and what are the step diameters?"), "setups");
  assert.equal(machineQuestion("what diameters?"), "sizes");
  assert.equal(machineQuestion("lead time?"), null);
});

import test from "node:test";
import assert from "node:assert/strict";
import { nextSteps, openingsLine, openingsNote, outcomeOf, repairHead, repairRefusal, signedPct } from "./repair-outcome.ts";

// The engine's own diagnosis of real files (backend tests/test_part_repair.py, staging run 2026-10-21).
const boredBlock = { kind: "face", open_edges: 945, welded_edges: 282, open_edges_after_weld: 663, loops: 2, largest_mm: 20, sizes_mm: [20, 6], part_mm: 20 } as const;
const unsewn = { kind: "seams", open_edges: 2576, welded_edges: 2520, open_edges_after_weld: 56, loops: 14, largest_mm: 0.37, sizes_mm: [0.37], part_mm: 30 } as const;
const plane = { kind: "surface", open_edges: 560, welded_edges: 0, open_edges_after_weld: 560, loops: 1, largest_mm: 20, sizes_mm: [20], part_mm: 20 } as const;
const gaps = { kind: "gaps", open_edges: 6, welded_edges: 0, open_edges_after_weld: 6, loops: 2, largest_mm: 3.54, sizes_mm: [3.54, 3.54], part_mm: 40 } as const;

test("the outcome is the engine's, and older answers still land in one", () => {
  assert.equal(outcomeOf({ outcome: "partly", repair_applied: false, repair_details: {} }), "partly");
  assert.equal(outcomeOf({ repair_applied: true, repair_details: { volume_change_pct: 0.1, volume_warning: null } }), "repaired");
  assert.equal(outcomeOf({ repair_applied: true, repair_details: { volume_change_pct: 10.4, volume_warning: "Repair changed the part's volume by +10.4%" } }), "closed_changed");
  assert.equal(outcomeOf({ repair_applied: true, repair_details: { volume_change_pct: null } }), "closed_changed", "an unmeasured change is not a clean repair");
  assert.equal(outcomeOf({ repair_applied: false, repair_details: { reason: "Repair timed out after 30 s." } }), "not_repaired");
});

test("headlines say what happened, with the volume when it moved", () => {
  assert.deepEqual(repairHead("repaired", 0.1), { chip: "Repaired", tone: "c-ok", title: "Repaired: a closed solid now" });
  assert.equal(repairHead("closed_changed", 10.4).title, "Closed, but the volume changed +10.4%");
  assert.equal(repairHead("closed_changed", -7.37).title, "Closed, but the volume changed −7.4%");
  assert.equal(repairHead("closed_changed", null).title, "Closed, but the change in shape is unknown");
  assert.equal(repairHead("partly", null).tone, "c-warn");
  assert.equal(repairHead("not_repaired", null).chip, "Not repaired");
  assert.equal(repairHead("not_needed", null).title, "Already a closed solid");
  assert.equal(signedPct(0.04), "0.0%");
});

test("what was open, in numbers the user can find in the file", () => {
  assert.equal(openingsLine(boredBlock), "A missing face, an opening 20 mm across, and 1 more (6 mm) · 945 open edges");
  assert.equal(openingsLine(unsewn), "Faces that touch but aren’t joined · 2,576 open edges, 2,520 of them on top of another");
  assert.equal(openingsLine(plane), "A surface with no thickness, 20 mm across · 560 open edges");
  assert.equal(openingsLine(gaps), "2 small gaps, the largest 3.5 mm across · 6 open edges");
  assert.equal(openingsLine({ ...boredBlock, loops: 6, sizes_mm: [20, 6, 5.9, 5.8, 5.7] }), "A missing face, an opening 20 mm across, and 5 more (6 mm, 5.9 mm, 5.8 mm, …) · 945 open edges");
  assert.equal(openingsLine({ ...gaps, kind: "none", open_edges: 0 }), null);
  assert.equal(openingsLine(undefined), null);
});

test("next steps: sewing only where it can work, then the CAD tool, then a fixed file", () => {
  assert.deepEqual(nextSteps("repaired", boredBlock, { brep: true, canHeal: true }), []);
  assert.deepEqual(nextSteps("not_needed", null, { brep: true, canHeal: true }), []);
  // Unsewn STEP faces: ScaleCAD's sewing first.
  const seams = nextSteps("not_repaired", unsewn, { brep: true, canHeal: true });
  assert.deepEqual(seams.map((s) => s.kind), ["heal", "cad", "upload"]);
  // A missing face can't be sewn back: CAD steps say to rebuild it.
  const face = nextSteps("not_repaired", boredBlock, { brep: true, canHeal: true });
  assert.deepEqual(face.map((s) => s.kind), ["cad", "upload"]);
  assert.match(face[0].why, /Rebuild the missing face/);
  // A surface: thicken it or export the solid.
  assert.match(nextSteps("not_repaired", plane, { brep: true, canHeal: true })[0].why, /Thicken the surface/);
  // An STL has no faces to sew.
  assert.deepEqual(nextSteps("partly", gaps, { brep: false, canHeal: false }).map((s) => s.kind), ["cad", "upload"]);
  // Closed but changed: keep the design's shape in CAD.
  const changed = nextSteps("closed_changed", boredBlock, { brep: true, canHeal: true });
  assert.deepEqual(changed.map((s) => s.kind), ["cad", "upload"]);
  assert.match(changed[0].why, /keep the design’s shape/);
  // Unknown openings (an older answer) are treated as gaps.
  assert.deepEqual(nextSteps("not_repaired", null, { brep: true, canHeal: true }).map((s) => s.kind), ["heal", "cad", "upload"]);
  assert.deepEqual(nextSteps("not_repaired", null, { brep: true, canHeal: false }).map((s) => s.kind), ["cad", "upload"]);
});

test("refusals before the repair runs read plainly", () => {
  const limit = repairRefusal(429, { detail: { code: "free_tool_limit", message: "Free accounts can run 10 mesh repairs an hour and 40 a day. You can run the next one in 23 minutes." } }, "x");
  assert.equal(limit.limit, true);
  assert.equal(limit.msg, "Free accounts can run 10 mesh repairs an hour and 40 a day. You can run the next one in 23 minutes. Pro and Pilot plans don’t have this limit.");
  assert.match(repairRefusal(404, { detail: "No stored source" }, "x").msg, /isn’t kept with the record/);
  assert.deepEqual(repairRefusal(500, null, "The repair didn’t finish."), { msg: "The repair didn’t finish.", limit: false });
});

test("the what-was-open line shows only where the outcome sentence leaves it out", () => {
  assert.equal(openingsNote("repaired", boredBlock), null);
  assert.equal(openingsNote("closed_changed", gaps), null);
  assert.equal(openingsNote("not_repaired", boredBlock), null, "the sentence already names the missing face and its size");
  assert.equal(openingsNote("not_repaired", plane), null);
  assert.equal(openingsNote("not_repaired", gaps), "2 small gaps, the largest 3.5 mm across · 6 open edges");
  assert.match(openingsNote("partly", unsewn) ?? "", /^Faces that touch but aren’t joined/);
});

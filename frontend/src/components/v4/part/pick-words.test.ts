import { test } from "node:test";
import assert from "node:assert/strict";

const { chosenLine, outsideName, problemsFigure, rowNote } = await import("./pick-words.ts");

const cost = {
  quantities: [1, 10, 100],
  estimates: [],
  routing: { archetype: "thin_wall_enclosure", recommended_process: "mjf", confidence: 0.6 },
  decision: { recommendation: { "10": { process: "fdm", material: "PLA", in_house: false, machine: null } } },
} as never;

test("the progress panel names the pick the part page opens with, not the router's route", () => {
  assert.equal(chosenLine(cost), "Filament printing (FDM/FFF) · ScaleCAD’s pick at 10");
  assert.equal(chosenLine(cost, 100), null);
  assert.equal(chosenLine(null), null);
});

test("one row carries the pick; the design-score best and the usual route aren't called picks", () => {
  const fdm = { code: "fdm", members: [1], geometryPick: false, routePick: false };
  const sls = { code: "sls", members: [1], geometryPick: true, routePick: false };
  const mjf = { code: "mjf", members: [1], geometryPick: false, routePick: true };
  assert.equal(rowNote(fdm, null, "fdm"), " · ScaleCAD’s pick");
  assert.equal(rowNote(sls, null, "fdm"), " · highest design score");
  assert.equal(rowNote(mjf, null, "fdm"), " · typical for the shape");
  assert.equal(rowNote(sls, "sls", "fdm"), " · your choice");
  assert.equal(rowNote(fdm, "sls", "fdm"), "");
  assert.equal(rowNote({ ...fdm, members: [1, 2] }, null, "fdm"), "");
});

test("the problems figure counts what the problem list counts", () => {
  assert.deepEqual(problemsFigure([]), { k: "Problems", v: "0", s: "none found", tone: "ok" });
  const nine = [...Array(5).fill({ severity: "error" }), ...Array(4).fill({ severity: "warning" })];
  assert.deepEqual(problemsFigure(nine), { k: "Problems", v: "9", s: "5 stop a process", tone: "warn" });
  assert.equal(problemsFigure([{ severity: "warning" }]).s, "none stops a process");
});

test("the outside quote says when it is your process at a job shop (buyer-02)", () => {
  assert.equal(outsideName({ process: "cnc_3axis", same_process: true }), "3-axis milling at a job shop");
  assert.equal(outsideName({ process: "cnc_5axis" }), "5-axis milling");
});

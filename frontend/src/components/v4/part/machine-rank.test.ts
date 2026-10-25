import test from "node:test";
import assert from "node:assert/strict";
import { machineSummary, pickedMachineId, rankMachines, shortWhy } from "./machine-rank.ts";
import type { MachineView } from "./model.ts";

function view(id: string, name: string, process: string, tone: MachineView["tone"], verdict: string, cost: number | null, why = ""): MachineView {
  return { id, name, process, sub: "", tone, verdict, cost, why, checks: "", envelope: null, method: null };
}

// me-08: stepped-shaft.step, Steel, at 100. The engine's in-house answer is turning on the Haas ST-20 at $23.39;
// the shop lists its machines VF-2, DMU 50, ST-20, Amada in the order they were added.
const shaft = [
  view("vf2", "Haas VF-2", "cnc_3axis", "ok", "Can make", 37.67),
  view("dmu", "DMG MORI DMU 50", "cnc_5axis", "ok", "Can make", 47.82),
  view("st20", "Haas ST-20", "cnc_turning", "ok", "Can make", 23.39),
  view("amada", "Amada HG-1003 press brake", "sheet_metal", "bad", "Can't", null, "Not makeable as drawn on this route."),
];

test("the In-house view leads with the machine the in-house answer is on, the others follow cheapest first (me-08)", () => {
  const id = pickedMachineId(shaft, { process: "cnc_turning", machine: "Haas ST-20" });
  assert.equal(id, "st20");
  assert.deepEqual(rankMachines(shaft, id).map((v) => v.name), ["Haas ST-20", "Haas VF-2", "DMG MORI DMU 50", "Amada HG-1003 press brake"]);
  // No in-house answer at this quantity: the machines that can make it still come cheapest first.
  assert.deepEqual(rankMachines(shaft, null).map((v) => v.id), ["st20", "vf2", "dmu", "amada"]);
  // A pick on a route none of the rows can make picks nothing; with two lathes it takes the one it names.
  assert.equal(pickedMachineId(shaft, { process: "sheet_metal", machine: "Amada HG-1003 press brake" }), null);
  const twoLathes = [...shaft, view("lb", "Okuma LB3000", "cnc_turning", "ok", "Can make", 25.1)];
  assert.equal(pickedMachineId(twoLathes, { process: "cnc_turning", machine: "Okuma LB3000" }), "lb");
  assert.equal(pickedMachineId(twoLathes, { process: "cnc_turning", machine: "Mazak QT" }), null);
  // One machine of yours on the route, named differently in the answer: that one.
  assert.equal(pickedMachineId(shaft, { process: "cnc_turning", machine: null }), "st20");
});

// me-10: bracket.step, Stainless, at 100. The Amada fits as far as it was declared but its heaviest part
// was never declared; the summary listed Can make VF-2, DMU 50 and Can't ST-20, and left the brake out.
const bracket = [
  view("vf2", "Haas VF-2", "cnc_3axis", "ok", "Can make", 55.95),
  view("dmu", "DMG MORI DMU 50", "cnc_5axis", "ok", "Can make", 71.2),
  view("st20", "Haas ST-20", "cnc_turning", "bad", "Can't", null, "Part lacks rotational geometry; required for cnc_turning."),
  view("amada", "Amada HG-1003 press brake", "sheet_metal", "warn", "Can't confirm", null, "max workpiece weight not declared. Declare it in Your shop to confirm."),
];

test("a machine left out of Can make says why in the summary, not only in its row (me-10)", () => {
  const ranked = rankMachines(bracket, pickedMachineId(bracket, { process: "cnc_3axis", machine: "Haas VF-2" }));
  assert.deepEqual(ranked.map((v) => v.id), ["vf2", "dmu", "amada", "st20"]);
  const groups = machineSummary(ranked);
  assert.deepEqual(groups.map((g) => g.k), ["Can make", "Can't confirm", "Can't"]);
  assert.equal(groups[0].names, "Haas VF-2, DMG MORI DMU 50");
  assert.equal(groups[0].why, null);
  assert.equal(groups[1].names, "Amada HG-1003 press brake");
  assert.equal(groups[1].why, "Max workpiece weight not declared");
  assert.equal(groups[2].why, "Can't make it as drawn");
  // Every machine is named exactly once across the summary.
  const named = groups.flatMap((g) => g.names.split(", "));
  assert.deepEqual([...named].sort(), bracket.map((v) => v.name).sort());
});

test("not set up, not compared and doesn't fit each keep their own reason", () => {
  const xs = [
    view("a", "Bambu Lab X1C", "fdm", "warn", "Not set up", null, "Declared for PETG, not PLA."),
    view("b", "Haas VF-2 #2", "cnc_3axis", "unk", "Another machine", null, "Your Haas VF-2 is the one checked for this route."),
    view("c", "BigRep ONE", "fdm", "bad", "Doesn't fit", null, "too big for your BigRep ONE: needs 1306 mm, has 1005 mm (longest)"),
  ];
  const groups = machineSummary(rankMachines(xs, null));
  assert.deepEqual(groups.map((g) => [g.k, g.why]), [
    ["Material not declared", "Declared for PETG, not PLA"],
    ["Not compared", "Your Haas VF-2 is the one checked for this route"],
    ["Can't", "Too big for your BigRep ONE: needs 1306 mm, has 1005 mm (longest)"],
  ]);
  // Several machines in one group: each named with its own reason.
  const two = machineSummary([xs[2], view("e", "Formlabs Form 4", "sla", "bad", "Can't", null, "x")]);
  assert.equal(two[0].why, "BigRep ONE: too big for your BigRep ONE: needs 1306 mm, has 1005 mm (longest) · Formlabs Form 4: can't make it as drawn");
  assert.equal(shortWhy(view("d", "X", "fdm", "unk", "Not checked", null, "")), "not checked");
});

import assert from "node:assert/strict";
import test from "node:test";
import {
  allowanceText,
  bucketBreakdown,
  breakdownOf,
  capabilityGroups,
  catalogAccess,
  filterRows,
  fitNote,
  hoursText,
  machineLine,
  massText,
  materialLine,
  partLine,
  planFiles,
  rowWords,
  sortRows,
  totalsText,
  zipEntryName,
  type BoardRow,
} from "./catalog-model.ts";

const row = (o: Partial<BoardRow>): BoardRow => ({
  item_id: "i",
  filename: "part.step",
  part_number: null,
  status: "completed",
  part_key: "k",
  analysis_id: "a",
  cost_decision_id: "d",
  quantity: 10,
  quantity_source: "run",
  verdict: "makeable_in_house",
  bucket: "in_house",
  reason: "On your Haas VF-2 · 6061-T6 Aluminum",
  route: { process: "cnc_3axis", machine: "Haas VF-2", owned: true },
  material: { declared: null, class: null, note: null, name: "6061-T6 Aluminum", mass_kg_each: 0.27, mass_basis: "x" },
  hours_each: 0.25,
  hours_total: 2.5,
  mass_kg_total: 2.7,
  unit_cost_usd: 30,
  total_cost_usd: 300,
  price_withheld: null,
  machine_rate_usd: 48.75,
  marginal: true,
  capability: null,
  cheaper_outside: null,
  duration_ms: 1000,
  error: null,
  ...o,
});

test("numbers read as an ops owner reads them, and a missing one stays missing", () => {
  assert.deepEqual([hoursText(0.004), hoursText(0.25), hoursText(1.31), hoursText(41.2), hoursText(1204), hoursText(null)], ["<1 min", "15 min", "1.3 h", "41 h", "1,204 h", "—"]);
  assert.deepEqual([massText(0.0089), massText(0.27), massText(1.274), massText(31.5), massText(312.4), massText(undefined)], ["9 g", "270 g", "1.27 kg", "31.5 kg", "312 kg", "—"]);
  // A tiny part (the engine's structured mass, 0.04 g) reads under a gram, never "1 g" or "0 g".
  assert.deepEqual([massText(0.0000412), massText(0.0006)], ["<1 g", "1 g"]);
});

test("a part's line leads with machine time, material and ownership, then the price", () => {
  const line = partLine(row({ quantity: 25, hours_total: 6.25, total_cost_usd: 750 }));
  assert.deepEqual(line, {
    time: "15 min each · 6.3 h for 25",
    material: "6061-T6 Aluminum · 270 g each",
    ownership: "Your Haas VF-2 · marginal $48.75/h",
    price: "$30.00 each · $750 for 25",
  });
  const outside = partLine(row({ bucket: "outside", route: { process: "fdm", machine: null, owned: false }, marginal: false }));
  assert.equal(outside.ownership, "Not owned · a filament printer would be an acquisition");
  const fit = partLine(row({ bucket: "new_machine", route: { process: "wire_edm", machine: null, owned: false }, capability: { process: "wire_edm", gate: "envelope", human: "x" } }));
  assert.equal(fit.ownership, "You own a wire EDM; too small for it");
  const qual = partLine(row({ bucket: "new_machine", route: { process: "cnc_3axis", machine: null, owned: false }, capability: { process: "cnc_3axis", gate: "material", need: "Delrin (POM)", human: "x" } }));
  assert.equal(qual.ownership, "You own a 3-axis mill; not qualified for Delrin (POM)");
  const regraded = partLine(row({ material: { declared: "ABS", class: "polymer", note: null, name: "Delrin (POM)", mass_kg_each: 1.2, mass_basis: "x" } }));
  assert.equal(regraded.material, "Delrin (POM) · 1.20 kg each · listed ABS");
  const same = partLine(row({ material: { declared: "PLA", class: "polymer", note: null, name: "PLA", mass_kg_each: 0.004, mass_basis: "x" } }));
  assert.equal(same.material, "PLA · 4 g each");
  const withheld = partLine(row({ unit_cost_usd: null, total_cost_usd: null, price_withheld: "Walls under 0.8 mm" }));
  assert.equal(withheld.price, "Withheld: Walls under 0.8 mm");
  const none = partLine(row({ bucket: "cant_make", hours_each: null, hours_total: null, unit_cost_usd: null, total_cost_usd: null, route: null, material: { declared: "304 SS", class: "stainless", note: null, name: null, mass_kg_each: null, mass_basis: null } }));
  assert.deepEqual(none, { time: "—", material: "304 SS", ownership: "—", price: "—" });
});

test("sorting by bucket keeps the four in order; by hours, cost or mass the biggest first and missing last", () => {
  const rows = [
    row({ filename: "c.stl", bucket: "cant_make", hours_total: null }),
    row({ filename: "a.stl", bucket: "in_house", hours_total: 1 }),
    row({ filename: "b.stl", bucket: "in_house", hours_total: 9 }),
    row({ filename: "n.stl", bucket: "new_machine", hours_total: 20 }),
    row({ filename: "o.stl", bucket: "outside", hours_total: null }),
  ];
  assert.deepEqual(sortRows(rows, "bucket").map((r) => r.filename), ["b.stl", "a.stl", "o.stl", "n.stl", "c.stl"]);
  assert.deepEqual(sortRows(rows, "hours").map((r) => r.filename), ["n.stl", "b.stl", "a.stl", "c.stl", "o.stl"]);
  assert.deepEqual(sortRows(rows, "name").map((r) => r.filename), ["a.stl", "b.stl", "c.stl", "n.stl", "o.stl"]);
});

test("filters by bucket and by words in the name, part number, reason or machine", () => {
  const rows = [row({ filename: "bracket.step", part_number: "BRK-1" }), row({ filename: "housing.stl", bucket: "outside", reason: "No machine of yours does resin printing", route: null })];
  assert.equal(filterRows(rows, "outside", "").length, 1);
  assert.equal(filterRows(rows, "all", "brk").length, 1);
  assert.equal(filterRows(rows, "all", "resin").length, 1);
  assert.equal(filterRows(rows, "all", "vf-2").length, 1);
  assert.equal(filterRows(rows, "in_house", "resin").length, 0);
});

test("parts needing a new machine group by the capability they lack", () => {
  const cap = (need: string) => ({ process: "cnc_3axis", gate: "material", need, human: `not qualified for ${need}` });
  const groups = capabilityGroups([
    row({ bucket: "new_machine", capability: cap("304 Stainless") }),
    row({ bucket: "new_machine", capability: cap("304 Stainless") }),
    row({ bucket: "new_machine", capability: { process: "fdm", gate: "envelope", human: "needs 300 mm" } }),
    row({ bucket: "in_house" }),
  ]);
  assert.deepEqual(groups.map((g) => [g.text, g.rows.length]), [["3-axis mill qualified for 304 Stainless", 2], ["Filament printer with a larger work area", 1]]);
});

test("bucket totals say how many parts each sum covers", () => {
  assert.equal(totalsText({ parts: 3, quantity: 30, hours: 41.2, hours_parts: 3, mass_kg: 12.4, mass_parts: 2, cost_usd: 3420, cost_parts: 3 }), "41 h · 12.4 kg (2 of 3) · $3,420");
  assert.equal(totalsText({ parts: 0, quantity: 0, hours: null, hours_parts: 0, mass_kg: null, mass_parts: 0, cost_usd: null, cost_parts: 0 }), "");
});

test("who may run one: pilot, a work email's free parts, or personal email", () => {
  assert.equal(catalogAccess({ plan: "pilot" }).kind, "pilot");
  assert.equal(catalogAccess({ plan: "trial", catalog: { eligible: false, unlimited: false, cap: 0 } }).kind, "personal");
  assert.equal(catalogAccess(null).kind, "unknown");
  const free = catalogAccess({ plan: "trial", phone_verification_required: true, catalog: { eligible: true, unlimited: false, cap: 50, used: 12, reserved: 0, remaining: 38 } });
  assert.equal(free.kind, "free");
  assert.equal(free.kind === "free" && free.phoneNeeded, true);
  assert.equal(allowanceText(free), "38 of 50 free catalog parts left");
  assert.equal(allowanceText(catalogAccess({ plan: "trial", catalog: { eligible: true, cap: 50, used: 0, reserved: 0, remaining: 50 } })), "50 free catalog parts");
  assert.equal(allowanceText(catalogAccess({ plan: "trial", catalog: { eligible: true, cap: 50, used: 50, reserved: 0, remaining: 0 } })), "All 50 free catalog parts used");
  assert.match(fitNote(52, free) ?? "", /^52 files and 38 free parts left/);
  assert.equal(fitNote(10, free), null);
});

test("picked files: CAD in, one ZIP alone, a CSV is the parts list, the rest named and left out", () => {
  const f = (name: string, size = 1000, path = name) => ({ name, size, path });
  const plan = planFiles([f("a.step"), f("b.STL"), f("c.igs", 0), f("d.sldprt"), f("notes.pdf"), f("parts.csv"), f(".DS_Store"), f("big.stp", 200 * 1024 * 1024), f("a.step", 1000, "a.step")]);
  assert.deepEqual(plan.cad.map((x) => x.name), ["a.step", "b.STL"]);
  assert.equal(plan.list?.name, "parts.csv");
  assert.deepEqual(plan.skipped, [
    { name: "c.igs", why: "empty file" },
    { name: "d.sldprt", why: "native CAD or drawing: export STEP" },
    { name: "notes.pdf", why: "not a CAD file" },
    { name: "big.stp", why: "over 100 MB" },
  ]);
  assert.equal(plan.problem, null);
  assert.equal(planFiles([f("set.zip"), f("a.step")]).problem, "Choose one ZIP, or loose files and folders, not both.");
  assert.equal(planFiles([f("notes.pdf")]).problem, "None of these is a STEP, STL or IGES file.");
  assert.match(planFiles([f("a.step", 5000)], { maxZipBytes: 1024 }).problem ?? "", /Split them into two runs/);
  assert.equal(planFiles([f("set.zip", 5000)]).zip?.name, "set.zip");
});

test("ZIP entry names keep the folder, never climb out of it", () => {
  assert.equal(zipEntryName({ name: "a.step", path: "catalog/brackets/a.step", size: 1 }), "catalog/brackets/a.step");
  assert.equal(zipEntryName({ name: "a.step", path: "../../etc/a.step", size: 1 }), "etc/a.step");
  assert.equal(zipEntryName({ name: "a.step", path: "", size: 1 }), "a.step");
});

test("the material a route uses leads, the part's own mass beside it when they differ", () => {
  const used = partLine(row({ material: { declared: null, class: null, note: null, name: "Mild Steel", mass_kg_each: 0.0471, mass_basis: "x", used_kg_each: 0.0518 } }));
  assert.equal(used.material, "Mild Steel · 52 g each · part 47 g");
  const same = partLine(row({ material: { declared: null, class: null, note: null, name: "PA12 (Nylon 12)", mass_kg_each: 0.024, mass_basis: "x", used_kg_each: 0.024 } }));
  assert.equal(same.material, "PA12 (Nylon 12) · 24 g each");
  assert.equal(totalsText({ parts: 2, quantity: 20, hours: 2, hours_parts: 2, mass_kg: 0.9, mass_parts: 2, used_kg: 1.04, used_parts: 2, cost_usd: 40, cost_parts: 2 }), "2.0 h · 1.04 kg · $40");
  const byMass = sortRows([row({ item_id: "a", filename: "a", used_kg_total: 1, mass_kg_total: 5 }), row({ item_id: "b", filename: "b", used_kg_total: 2, mass_kg_total: 1 })], "mass");
  assert.deepEqual(byMass.map((r) => r.item_id), ["b", "a"]);
});

test("a bucket's breakdown: hours by machine, material by grade, what a new machine needs", () => {
  const rows = [
    row({ item_id: "1", hours_total: 2.5, used_kg_total: 1.2, mass_kg_total: 0.9 }),
    row({ item_id: "2", hours_total: null, used_kg_total: null, mass_kg_total: 0.3 }),
    row({ item_id: "3", route: { process: "mjf", machine: "HP Jet Fusion 5200", owned: true }, hours_total: 7, used_kg_total: 0.4, mass_kg_total: 0.4, material: { declared: null, class: null, note: null, name: "PA12 (Nylon 12)", mass_kg_each: 0.04, mass_basis: "x" } }),
    row({ item_id: "4", bucket: "outside", route: { process: "fdm", machine: null, owned: false }, hours_total: 5, material: { declared: null, class: null, note: null, name: "PLA", mass_kg_each: 0.01, mass_basis: "x" } }),
    row({ item_id: "5", bucket: "new_machine", route: { process: "cnc_3axis", machine: null, owned: false }, hours_total: 3, capability: { process: "cnc_3axis", gate: "material", need: "Delrin (POM)", human: "not qualified for Delrin (POM)" } }),
    row({ item_id: "6", bucket: "new_machine", route: { process: "cnc_3axis", machine: null, owned: false }, hours_total: null, capability: { process: "cnc_3axis", gate: "material", need: "Delrin (POM)", human: "not qualified for Delrin (POM)" } }),
  ];
  const ih = bucketBreakdown(rows, "in_house");
  assert.deepEqual(ih.machines.map((m) => [m.machine, m.parts, m.hours, m.hours_parts]), [["HP Jet Fusion 5200", 1, 7, 1], ["Haas VF-2", 2, 2.5, 1]]);
  assert.deepEqual(machineLine(ih.machines[1]), { label: "On Haas VF-2", value: "2 parts · 2.5 h (1 of 2)" });
  assert.deepEqual(ih.materials.map((g) => [g.material, g.parts, g.used_kg, g.part_kg]), [["6061-T6 Aluminum", 2, 1.2, 1.2], ["PA12 (Nylon 12)", 1, 0.4, 0.4]]);
  assert.deepEqual(materialLine(ih.materials[0]), { label: "6061-T6 Aluminum", value: "1.20 kg used (1 of 2) · 2 parts" });
  const out = bucketBreakdown(rows, "outside");
  assert.deepEqual(machineLine(out.machines[0]), { label: "Filament printing, not owned", value: "1 part · 5.0 h" });
  assert.deepEqual(materialLine(out.materials[0]), { label: "PLA", value: "2.70 kg in the parts · 1 part" });
  const nm = bucketBreakdown(rows, "new_machine");
  assert.deepEqual(nm.missing.map((g) => [g.process, g.gate, g.need, g.parts, g.hours]), [["cnc_3axis", "material", "Delrin (POM)", 2, 3]]);
  // The server's breakdown wins when the board carries one.
  const board = { rows, breakdown: { in_house: { machines: [], materials: [], missing: [] } } } as never;
  assert.deepEqual(breakdownOf(board, "in_house").machines, []);
  assert.equal(breakdownOf({ rows } as never, "in_house").machines.length, 2);
});

test("a row's engine words read in the person's unit; its file name never changes", () => {
  const r = row({
    filename: "150-fit-box-60mm.stl",
    bucket: "outside",
    reason: "24 faces (100.0%) below 0.8mm min wall for fdm",
    unit_cost_usd: null,
    price_withheld: "walls under 0.8 mm",
    body: { file: "frame-40mm.stl", ids: [1], copies: 2, of: 4, shape: "Square tube 40 × 40 × 3 mm, 600 mm long", name: "Tube 600mm" },
  } as Partial<BoardRow>);
  const inch = rowWords(r, "in", "Flatness 0.05 mm");
  assert.equal(inch.reason, "24 faces (100.0%) below 0.031 in min wall for fdm");
  assert.equal(inch.body, "Tube 600mm of 4 in frame-40mm.stl · 2 per file · Square tube 1.575 × 1.575 × 0.118 in, 23.62 in long", "names keep their mm");
  assert.equal(inch.spec, "Flatness 0.002 in");
  assert.equal(inch.price, "Withheld: walls under 0.031 in");
  assert.equal(r.filename, "150-fit-box-60mm.stl");
  const mm = rowWords(r, "mm");
  assert.equal(mm.reason, "24 faces (100.0%) below 0.8mm min wall for fdm");
  assert.equal(mm.price, "Withheld: walls under 0.8 mm");
  assert.equal(mm.spec, null);
});

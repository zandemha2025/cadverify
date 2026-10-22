import assert from "node:assert/strict";
import test from "node:test";

import {
  envelopeOf,
  sizeFieldsIn,
  sizeFieldsToMm,
  hoursShort,
  loadFor,
  loadRows,
  loadTile,
  isoBox,
  machineStatus,
  opOn,
  opSavedNote,
  perHour,
  procName,
  rateCardView,
  tileSub,
  toggleOp,
  versionInEffect,
} from "./shop-derive.ts";

const vf2 = {
  name: "Haas VF-2",
  process: "cnc_3axis",
  count: 1,
  hourly_rate_usd: 85,
  max_workpiece_kg: 200,
  capabilities: { x: 762, y: 406, z: 508, axes: 3 },
};

test("every method has a plain name; unknown ids pass through", () => {
  assert.equal(procName("cnc_turning"), "Turning");
  assert.equal(procName("mjf"), "Nylon powder printing (MJF)");
  assert.equal(procName("plasma"), "plasma");
});

test("status says owned with or without a declared rate", () => {
  assert.deepEqual(machineStatus(vf2), { label: "Owned · rate declared", rated: true });
  assert.deepEqual(machineStatus({ hourly_rate_usd: null }), { label: "Owned · no rate", rated: false });
  // A declared rate of 0 is still a declaration.
  assert.equal(machineStatus({ hourly_rate_usd: 0 }).rated, true);
});

test("envelope reads the keys the API stores, lathe swing first", () => {
  assert.equal(envelopeOf(vf2)?.text, "762 × 406 × 508 mm");
  const lathe = envelopeOf({ process: "cnc_turning", capabilities: { swing_dia: 254, between_centers: 533 } });
  assert.equal(lathe?.text, "Ø254 × 533 mm");
  assert.equal(lathe?.label, "Swing × between centers");
  // A lathe saved before the swing keys still shows what was declared, labelled as such.
  const legacy = envelopeOf({ process: "cnc_turning", capabilities: { x: 254, y: 254, z: 533 } });
  assert.equal(legacy?.label, "Work area (declared X × Y × Z)");
  assert.equal(envelopeOf({ process: "cnc_3axis", capabilities: {} }), null);
  assert.equal(envelopeOf({ process: "cnc_3axis", capabilities: { x: "762", y: 406 } }), null);
});

test("work areas and lathe sizes read in the person's unit; the drawing stays in mm", () => {
  const inch = envelopeOf(vf2, "in")!;
  // Inches without trailing zeros (me-22: "120.0 × 48.00 × 12.00 in").
  assert.equal(inch.text, "30 × 15.98 × 20 in");
  assert.equal(inch.fig, "30×15.98×20");
  assert.equal(inch.unit, "in");
  assert.deepEqual([inch.w, inch.d, inch.h], [762, 406, 508], "the drawing's extents stay in mm");
  assert.equal(envelopeOf(vf2, "mm")?.fig, "762×406×508");
  assert.equal(envelopeOf({ process: "cnc_turning", capabilities: { swing_dia: 254, between_centers: 533 } }, "in")?.text, "Ø10 × 20.98 in");
  assert.equal(envelopeOf({ process: "fdm", capabilities: { x: 256, y: 256, z: 256 } }, "in")?.text, "10.08 × 10.08 × 10.08 in");
  assert.equal(envelopeOf({ process: "sheet_metal", capabilities: { x: 3048, y: 1219.2, z: 304.8 } }, "in")?.text, "120 × 48 × 12 in");
});

test("a press brake reads as its bend length and press force, a cutter as its bed (me-02)", () => {
  const brake = envelopeOf({ process: "sheet_metal", capabilities: { sheet_kind: "press_brake", max_bend_length_mm: 3048, tonnage_t: 100 } }, "in")!;
  assert.equal(brake.text, "120 in bend length · 110.23 US tons");
  assert.equal(brake.label, "Press brake");
  assert.equal(envelopeOf({ process: "sheet_metal", capabilities: { sheet_kind: "press_brake", max_bend_length_mm: 3048, tonnage_t: 100 } }, "mm")?.text, "3048 mm bend length · 100 t");
  const laser = envelopeOf({ process: "sheet_metal", capabilities: { sheet_kind: "laser", bed_x: 3048, bed_y: 1524 } }, "in")!;
  assert.equal(laser.text, "120 × 60 in");
  assert.equal(laser.label, "Bed");
  assert.equal(tileSub({ name: "Amada", process: "sheet_metal", count: 1, hourly_rate_usd: 70, max_workpiece_kg: 22.679619, capabilities: { sheet_kind: "press_brake" } }, "in"), "Press brake · ×1 · $70/h · 50 lb max");
  assert.equal(tileSub({ name: "Old", process: "sheet_metal", count: 1, hourly_rate_usd: null, max_workpiece_kg: 23, capabilities: {} }), "Sheet-metal machine · ×1 · no rate · 23 kg max");
});

test("the machine form shows sizes in inches and saves millimetres, exactly as they were when unchanged", () => {
  const mm = { x: "762", y: "406", z: "508", swing: "", between: "" };
  const shown = sizeFieldsIn(mm, "in");
  assert.deepEqual(shown, { x: "30", y: "15.98", z: "20", swing: "", between: "" });
  assert.deepEqual(sizeFieldsIn(mm, "mm"), mm);
  // Nothing changed: the declared millimetres go back as they were, not 405.892 from a rounded 15.98 in.
  assert.deepEqual(sizeFieldsToMm(shown, shown, mm, "in"), mm);
  // A changed field is read in inches, or in the unit typed with it; a cleared one is cleared.
  assert.deepEqual(sizeFieldsToMm({ ...shown, x: "40", y: "300 mm", z: "" }, shown, mm, "in"), { x: "1016", y: "300", z: "", swing: "", between: "" });
  assert.deepEqual(sizeFieldsToMm({ ...shown, x: "12.5\"" }, shown, mm, "in").x, "317.5");
  // Text that isn't a length goes on as typed, so the form's own check names the field.
  assert.equal(sizeFieldsToMm({ ...shown, x: "wide" }, shown, mm, "in").x, "wide");
  assert.deepEqual(sizeFieldsToMm({ ...mm, x: "800" }, mm, mm, "mm"), { ...mm, x: "800" });
});

test("the drawing fits the 300 × 150 view box for very different shapes", () => {
  for (const [w, d, h] of [[762, 406, 508], [256, 256, 256], [1800, 1000, 700], [50, 50, 1000], [1000, 1000, 5]]) {
    const nums = Object.values(isoBox(w, d, h)).join(" ").match(/-?\d+(\.\d+)?/g)!.map(Number);
    const xs = nums.filter((_, i) => i % 2 === 0);
    const ys = nums.filter((_, i) => i % 2 === 1);
    assert.ok(Math.min(...xs) >= 0 && Math.max(...xs) <= 300, `x in box for ${w}×${d}×${h}`);
    assert.ok(Math.min(...ys) >= 0 && Math.max(...ys) <= 150, `y in box for ${w}×${d}×${h}`);
  }
});

test("tile line never invents a rate or weight", () => {
  assert.equal(tileSub(vf2), "3-axis milling · ×1 · $85/h · 200 kg max");
  assert.equal(tileSub({ ...vf2, process: "cnc_turning", hourly_rate_usd: null, max_workpiece_kg: null, count: null }), "Lathe · ×1 · no rate");
  assert.equal(perHour(85.5), "$85.50/h");
});

test("shop ops: toggling one keeps the others and a declared limits object", () => {
  const ops = { hip: { dia_mm: 300, height_mm: 600 }, grinding: true, anodize: true, sinter: false };
  assert.equal(opOn(ops, "hip"), true);
  assert.equal(opOn(ops, "sinter"), false);
  assert.deepEqual(toggleOp(ops, "sinter"), { ...ops, sinter: true });
  const off = toggleOp(ops, "grinding");
  assert.deepEqual(off, { hip: { dia_mm: 300, height_mm: 600 }, anodize: true, sinter: false });
});

test("shop ops: a machine's own step counts as in-house until it's turned off, then it's sent out", () => {
  // Round 7: stress relief and sintering, never said, read as done in-house (the engine assumes it).
  assert.equal(opOn({}, "stress_relief"), true);
  assert.equal(opOn({}, "sinter"), true);
  assert.equal(opOn({}, "hip"), false);
  assert.equal(opOn({}, "grinding"), false);
  // Turned off: declared sent out (false), never just forgotten (which would read in-house again).
  const sent = toggleOp({ grinding: true }, "stress_relief");
  assert.deepEqual(sent, { grinding: true, stress_relief: false });
  assert.equal(opOn(sent, "stress_relief"), false);
  assert.equal(opSavedNote("Stress relief", sent, "stress_relief"), "Stress relief is sent out; parts that need it are still made on your machines.");
  assert.deepEqual(toggleOp(sent, "stress_relief"), { grinding: true, stress_relief: true });
  assert.equal(opSavedNote("HIP", {}, "hip"), "HIP isn't done in-house.");
  assert.equal(opSavedNote("Grinding", { grinding: true }, "grinding"), "Grinding is done in-house.");
});

test("rate card: default v0 with nothing authored", () => {
  const v = rateCardView({ using_governed: false, flag_enabled: true }, []);
  assert.equal(v?.chip, "Default v0");
  assert.equal(v?.chipLong, "Default v0 · none authored");
  assert.equal(v?.aria, "Rate card: default v0, none authored. Show details");
  assert.equal(v?.counts, "Built-in default rates. 0 versions authored, 0 published.");
  assert.equal(rateCardView(null, []), null);
});

test("rate card: authored drafts are not in effect until published", () => {
  const v = rateCardView({ using_governed: false, flag_enabled: true }, [{ id: 2, version: 2, status: "draft" }, { id: 1, version: 1, status: "draft" }]);
  assert.equal(v?.chipLong, "Default v0 · 2 authored, none in effect");
  assert.equal(v?.drafts, 2);
});

test("rate card: governed names the version in effect now", () => {
  const now = Date.parse("2026-10-18T12:00:00Z");
  const versions = [
    { id: 3, version: 3, status: "published", effective_from: "2026-11-01T00:00:00Z" },
    { id: 2, version: 2, status: "published", effective_from: "2026-10-01T00:00:00Z" },
    { id: 1, version: 1, status: "archived", effective_from: "2026-09-01T00:00:00Z" },
  ];
  assert.equal(versionInEffect(versions, now)?.version, 2);
  const v = rateCardView({ using_governed: true, flag_enabled: true }, versions, now);
  assert.equal(v?.chip, "Governed · 2 published");
  assert.equal(v?.chipLong, "Governed · v2 in effect");
  assert.equal(v?.title, "Rate card v2");
});

test("machine load: the tile line, the sheet's rows, matched by machine name", () => {
  const haas = { machine: "Haas VF-2", parts: 3, hours: 30, hours_parts: 2, decided_parts: 2, decided_hours: 5, default_parts: 1, default_hours: 25, stale_parts: 0 };
  assert.equal(loadFor([haas], "Haas VF-2"), haas);
  assert.equal(loadFor([haas], "Haas ST-20"), null);
  assert.equal(loadTile(haas), "30 h of work · 3 parts");
  assert.equal(loadTile(null), "No checked parts on it");
  assert.equal(loadTile({ ...haas, hours: null, hours_parts: 0 }), "3 parts · machine time not estimated");
  assert.deepEqual(loadRows(haas, 100), [
    ["Machine time", "30 h (2 of 3 parts) · 3 parts"],
    ["Recorded in-house", "2 parts · 5 h at their quantities"],
    ["Not decided yet", "1 part · 25 h at the quantity checked, else 100 of each"],
  ]);
  assert.deepEqual(loadRows({ ...haas, parts: 0 }, 100), []);
  assert.deepEqual([hoursShort(0.0002), hoursShort(0.5), hoursShort(2.41), hoursShort(1204.4), hoursShort(null)], ["<1 min", "30 min", "2.4 h", "1,204 h", "—"]);
});

import test from "node:test";
import assert from "node:assert/strict";
import { KG_PER_LB, T_PER_US_TON, backToBase, readingsLine, forceIn, mergeSheetCapabilities, sheetKindName, sheetKindOf, thickMapToSave, thickRowsFrom, weightIn } from "./machine-kinds.ts";

test("a sheet-metal machine says what it is; one that never said reads as a sheet-metal machine (me-02)", () => {
  assert.equal(sheetKindOf({ sheet_kind: "press_brake" }), "press_brake");
  assert.equal(sheetKindOf({ sheet_kind: "brake" }), null);
  assert.equal(sheetKindName("sheet_metal", { sheet_kind: "laser" }), "Laser cutter");
  assert.equal(sheetKindName("sheet_metal", { x: 3048 }), "Sheet-metal machine");
  assert.equal(sheetKindName("cnc_3axis", { sheet_kind: "laser" }), null);
});

test("her brake in her units: 3/16 in stainless, 1/4 in steel, press force in US tons, heaviest part in lb", () => {
  // 3/16 in = 0.1875 in × 25.4 = 4.7625 mm; 1/4 in = 6.35 mm.
  const { map, errors } = thickMapToSave(null, { steel: "1/4", stainless: "3/16", aluminum: "" }, { steel: "", stainless: "", aluminum: "" }, "in");
  assert.deepEqual(errors, {});
  assert.deepEqual(map, { steel: 6.35, stainless: 4.7625 });
  // Shown back in inches exactly as typed in decimals.
  assert.deepEqual(thickRowsFrom(map, "in"), { steel: "0.25", stainless: "0.1875", aluminum: "" });
  assert.deepEqual(thickRowsFrom(map, "mm"), { steel: "6.35", stainless: "4.763", aluminum: "" });
  // 100 metric t = 100 ÷ 0.90718474 = 110.23 US tons; 110 US tons typed = 99.790321 t.
  assert.equal(forceIn(100, "in"), "110.23");
  assert.equal(forceIn(100, "mm"), "100");
  assert.equal(backToBase("110", "110.23", "100", T_PER_US_TON), "99.790321");
  // Untouched, it saves exactly what it was (no round trip through a rounded display).
  assert.equal(backToBase("110.23", "110.23", "100", T_PER_US_TON), "100");
  // 23 kg = 50.7 lb shown; 50 lb typed = 22.679619 kg.
  assert.equal(weightIn(23, "in"), "50.7");
  assert.equal(backToBase("50", "50.7", "23", KG_PER_LB), "22.679619");
  assert.equal(backToBase("", "50.7", "23", KG_PER_LB), "");
  assert.equal(backToBase("fifty", "50.7", "23", KG_PER_LB), "fifty");
});

test("thickness rows keep what they didn't show and say which row is wrong", () => {
  const base = { "@titanium": 2, stainless: 4.7625 };
  const rows = thickRowsFrom(base, "in");
  const same = thickMapToSave(base, rows, rows, "in");
  assert.deepEqual(same.map, base);
  const cleared = thickMapToSave(base, { ...rows, stainless: "" }, rows, "in");
  assert.deepEqual(cleared.map, { "@titanium": 2 });
  const bad = thickMapToSave(base, { ...rows, steel: "quarter" }, rows, "in");
  assert.equal(bad.errors.steel, "Steel: a thickness like 0.1875 or 3/16.");
});

test("choosing a kind replaces the work-area box with the kind's own fields", () => {
  const amada = { x: 3048, y: 1219.2, z: 304.8, maker_spec: { catalog: "x", fields: ["max_workpiece_kg"] } };
  assert.deepEqual(mergeSheetCapabilities(amada, "press_brake", { bend: 3048, tonnage: 100 }), {
    maker_spec: { catalog: "x", fields: ["max_workpiece_kg"] },
    sheet_kind: "press_brake",
    max_bend_length_mm: 3048,
    tonnage_t: 100,
  });
  assert.deepEqual(mergeSheetCapabilities({ sheet_kind: "press_brake", tonnage_t: 100 }, "laser", { bedX: 3000, bedY: 1500 }), { sheet_kind: "laser", bed_x: 3000, bed_y: 1500 });
  // No kind chosen (an older machine kept as it was): nothing changes.
  assert.deepEqual(mergeSheetCapabilities(amada, null, {}), amada);
});

test("a save says how it read the grades it had no price of their own for (me-01)", () => {
  const line = readingsLine([
    { typed: "6061", as: "6061-T6 Aluminum", note: null },
    { typed: "303", as: "304 Stainless", note: "ScaleCAD has no 303 price; read as 304 Stainless, the closest stainless it prices" },
    { typed: "316", as: "SS316L", note: "316 is read as 316L (SS316L), the 316 stainless ScaleCAD prices" },
  ]);
  assert.equal(line, "Materials read as 303 → 304 Stainless, 316 → SS316L. ScaleCAD has no 303 price; read as 304 Stainless, the closest stainless it prices. 316 is read as 316L (SS316L), the 316 stainless ScaleCAD prices.");
  assert.equal(readingsLine([{ typed: "6061", as: "6061-T6 Aluminum", note: null }]), null);
  assert.equal(readingsLine(undefined), null);
  // op-03: brass and bronze stay on the machine as typed, said not priced yet; ductile iron says what it's priced as.
  assert.equal(
    readingsLine([
      { typed: "Brass C360", as: null, note: "ScaleCAD doesn't price brass yet: Brass C360 stays on the machine, and a brass part shows as not priced yet" },
      { typed: "ductile iron", as: "Mild Steel", note: "ScaleCAD has no iron price on a 3-axis mill; ductile iron is read as Mild Steel, the steel it prices an iron part in there" },
    ]),
    "Materials read as ductile iron → Mild Steel. ScaleCAD doesn't price brass yet: Brass C360 stays on the machine, and a brass part shows as not priced yet. ScaleCAD has no iron price on a 3-axis mill; ductile iron is read as Mild Steel, the steel it prices an iron part in there.",
  );
});

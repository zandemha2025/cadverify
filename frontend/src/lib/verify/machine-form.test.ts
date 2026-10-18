import assert from "node:assert/strict";
import test from "node:test";

import {
  capitalPercentText,
  envelopeFieldsFrom,
  mergeMachineCapabilities,
  mergePrinterCapabilities,
  parseCapitalPercent,
  parseMachineNumbers,
  parsePrinterDetails,
  printerFieldsFor,
  printerFieldsFrom,
  type MachineNumberInput,
  type PrinterText,
} from "./machine-form.ts";

const base: MachineNumberInput = {
  count: "1",
  rate: "95.50",
  maxKg: "250",
  x: "762",
  y: "406",
  z: "508",
  swing: "",
  between: "",
  isTurning: false,
};

test("strict machine form parser preserves valid numeric declarations", () => {
  const result = parseMachineNumbers(base);
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.deepEqual(result.value, {
    count: 1,
    rate: 95.5,
    maxKg: 250,
    capabilities: { x: 762, y: 406, z: 508 },
  });
});

test("malformed numeric prefixes never coerce into persisted values", () => {
  for (const [field, value] of [
    ["count", "2 machines"],
    ["rate", "95/hr"],
    ["x", "12abc"],
    ["y", "0x10"],
    ["z", "Infinity"],
  ] as const) {
    const result = parseMachineNumbers({ ...base, [field]: value });
    assert.equal(result.ok, false, `${field}=${value} should be rejected`);
    if (result.ok) continue;
    assert.match(result.errors[field] ?? "", /complete number|finite/);
  }
});

test("boundary rules match the backend machine contract", () => {
  const result = parseMachineNumbers({
    ...base,
    count: "1.5",
    rate: "-0.01",
    maxKg: "0",
    x: "-1",
  });
  assert.equal(result.ok, false);
  if (result.ok) return;
  assert.match(result.errors.count ?? "", /whole number/);
  assert.match(result.errors.rate ?? "", /at least 0/);
  assert.match(result.errors.maxKg ?? "", /greater than 0/);
  assert.match(result.errors.x ?? "", /greater than 0/);
});

test("blank optional values remain unknown rather than fabricated", () => {
  const result = parseMachineNumbers({
    ...base,
    rate: "",
    maxKg: "",
    x: "",
    y: "",
    z: "",
  });
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.equal(result.value.rate, null);
  assert.equal(result.value.maxKg, null);
  assert.deepEqual(result.value.capabilities, {});
});

test("turning fields are selected without leaking stale mill envelope values", () => {
  const result = parseMachineNumbers({
    ...base,
    isTurning: true,
    swing: "300",
    between: "600",
  });
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.deepEqual(result.value.capabilities, { swing_dia: 300, between_centers: 600 });
});

// Catalog prefill used to keep only x/y/z, so a DMU 50 saved from the catalog
// lost axes/motion_mode and read `unknown` on every 5-axis part.
test("a catalog prefill submits every template capability, not just the envelope", () => {
  const template = {
    x: 500, y: 450, z: 400, axes: 5, motion_mode: "simultaneous_5",
    min_layer_um: 40, min_feature_mm: 0.1,
  };
  const result = parseMachineNumbers({ ...base, ...envelopeFieldsFrom(template) });
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.deepEqual(mergeMachineCapabilities(template, result.value.capabilities, false), template);
});

// Editing a lathe used to delete x/y/z (and anything else outside the turning
// fields), so even a rate-only edit left the lathe `unknown`.
test("editing a lathe preserves its envelope and every capability the form hides", () => {
  for (const stored of [
    { x: 254, y: 254, z: 533, achievable_it_grade: 8 }, // saved before lathes used swing keys
    { swing_dia: 254, between_centers: 533, live_tooling: true },
  ]) {
    const result = parseMachineNumbers({ ...base, rate: "80", ...envelopeFieldsFrom(stored), isTurning: true });
    assert.equal(result.ok, true);
    if (!result.ok) continue;
    assert.deepEqual(mergeMachineCapabilities(stored, result.value.capabilities, true), stored);
  }
});

test("a lathe edit shows the stored swing/length instead of blank fields", () => {
  const fields = envelopeFieldsFrom({ swing_dia: 254, between_centers: 533 });
  assert.equal(fields.swing, "254");
  assert.equal(fields.between, "533");
});

test("clearing a visible envelope field removes only that key", () => {
  const stored = { swing_dia: 254, between_centers: 533, x: 1, y: 2, z: 3 };
  const result = parseMachineNumbers({ ...base, x: "", y: "", z: "", swing: "300", between: "", isTurning: true });
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.deepEqual(mergeMachineCapabilities(stored, result.value.capabilities, true), {
    swing_dia: 300, x: 1, y: 2, z: 3,
  });
});

// ── capital fraction and printer details ────────────────────────────────────

test("capital fraction is typed as a percent and stored as a fraction", () => {
  assert.deepEqual(parseCapitalPercent("35"), { value: 0.35 });
  assert.deepEqual(parseCapitalPercent(" 12.5 % "), { value: 0.125 });
  assert.deepEqual(parseCapitalPercent(""), { value: null });
  assert.match(parseCapitalPercent("101").error ?? "", /between 0 and 100/);
  assert.match(parseCapitalPercent("35abc").error ?? "", /complete number/);
  assert.equal(capitalPercentText(0.35), "35");
  assert.equal(capitalPercentText(0.125), "12.5");
  assert.equal(capitalPercentText(null), "");
});

const blankPrinter: PrinterText = { nozzle: "", layerMin: "", layerMax: "", enclosure: "", chamber: "", stocked: "" };

test("printer fields follow the method: nozzle and enclosure on filament only", () => {
  assert.deepEqual(printerFieldsFor("fdm"), { nozzle: true, layers: true, enclosure: true, stocked: true, any: true });
  assert.deepEqual(printerFieldsFor("sla"), { nozzle: false, layers: true, enclosure: false, stocked: true, any: true });
  assert.deepEqual(printerFieldsFor("mjf"), { nozzle: false, layers: true, enclosure: false, stocked: false, any: true });
  assert.equal(printerFieldsFor("cnc_3axis").any, false);
  assert.equal(printerFieldsFor("ded").any, false);
});

test("printer details round-trip: mm in the form, µm in the capability bag", () => {
  const text: PrinterText = { nozzle: "0.4", layerMin: "0.08", layerMax: "0.28", enclosure: "heated", chamber: "60", stocked: "PETG, PLA, PETG" };
  const r = parsePrinterDetails(text, "fdm");
  assert.equal(r.ok, true);
  if (!r.ok) return;
  assert.deepEqual(r.value, {
    nozzle_dia_mm: 0.4, min_layer_um: 80, max_layer_um: 280,
    enclosure: "heated", max_chamber_c: 60, stocked_materials: ["PETG", "PLA"],
  });
  const back = printerFieldsFrom(r.value);
  assert.deepEqual(back, { ...text, stocked: "PETG, PLA" });
  // Catalog layer heights such as 0.0125 mm survive the µm conversion.
  const fine = parsePrinterDetails({ ...blankPrinter, layerMin: "0.0125" }, "sla");
  assert.ok(fine.ok && fine.value.min_layer_um === 12.5);
  assert.equal(printerFieldsFrom({ min_layer_um: 12.5 }).layerMin, "0.0125");
});

test("only the printer fields shown are checked; malformed ones are reported", () => {
  // A chamber temperature is ignored unless the chamber is heated.
  const enclosed = parsePrinterDetails({ ...blankPrinter, enclosure: "enclosed", chamber: "hot" }, "fdm");
  assert.ok(enclosed.ok && enclosed.value.enclosure === "enclosed" && !("max_chamber_c" in enclosed.value));
  // A resin printer has no nozzle field, so a stale nozzle value is not read.
  const resin = parsePrinterDetails({ ...blankPrinter, nozzle: "x" }, "sla");
  assert.ok(resin.ok && !("nozzle_dia_mm" in resin.value));
  const bad = parsePrinterDetails({ ...blankPrinter, nozzle: "0.4mm", layerMin: "0.3", layerMax: "0.1", enclosure: "heated", chamber: "-5" }, "fdm");
  assert.equal(bad.ok, false);
  if (bad.ok) return;
  assert.match(bad.errors.nozzle ?? "", /complete number/);
  assert.match(bad.errors.layerMax ?? "", /at least the finest/);
  assert.match(bad.errors.chamber ?? "", /greater than 0/);
});

test("merging printer details keeps every other capability and drops keys the method can't carry", () => {
  const stored = { x: 256, y: 256, z: 256, min_feature_mm: 0.4, nozzle_dia_mm: 0.4, enclosure: "heated", max_chamber_c: 60, stocked_materials: ["PLA"], min_layer_um: 40, max_layer_um: 400 };
  // An FDM edit that clears the chamber and stock replaces only the printer keys it shows.
  const parsed = parsePrinterDetails({ ...printerFieldsFrom(stored), enclosure: "enclosed", stocked: "" }, "fdm");
  assert.ok(parsed.ok);
  if (!parsed.ok) return;
  assert.deepEqual(mergePrinterCapabilities(stored, parsed.value, "fdm"), {
    x: 256, y: 256, z: 256, min_feature_mm: 0.4, nozzle_dia_mm: 0.4, enclosure: "enclosed", min_layer_um: 40, max_layer_um: 400,
  });
  // Switching the method to resin drops the filament-only keys the API would refuse.
  const resin = parsePrinterDetails(printerFieldsFrom(stored), "sla");
  assert.ok(resin.ok);
  if (!resin.ok) return;
  assert.deepEqual(mergePrinterCapabilities(stored, resin.value, "sla"), {
    x: 256, y: 256, z: 256, min_feature_mm: 0.4, stocked_materials: ["PLA"], min_layer_um: 40, max_layer_um: 400,
  });
  // A milling machine keeps an older min_layer_um it was saved with; nothing else is invented.
  assert.deepEqual(mergePrinterCapabilities({ x: 1, min_layer_um: 40 }, {}, "cnc_3axis"), { x: 1, min_layer_um: 40 });
});

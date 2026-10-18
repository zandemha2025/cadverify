import assert from "node:assert/strict";
import test from "node:test";

import {
  envelopeFieldsFrom,
  mergeMachineCapabilities,
  parseMachineNumbers,
  type MachineNumberInput,
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

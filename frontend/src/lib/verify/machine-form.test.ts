import assert from "node:assert/strict";
import test from "node:test";

import { parseMachineNumbers, type MachineNumberInput } from "./machine-form.ts";

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

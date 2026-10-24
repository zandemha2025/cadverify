import test from "node:test";
import assert from "node:assert/strict";
import { rowMustHold, rowSignoffLine, rowSpecLine } from "./row-specs.ts";

const specs = {
  summary: ["Finish: Anodize, Type II, Ra 1.6 µm", "Heat treatment: Stress relief", "Inspection: Standard inspection", "Supplier must hold: AS9100, ITAR registration"],
  supplier_must_hold: ["AS9100", "ITAR registration"],
  excluded_processes: [],
};

test("a row's specs read as one line, without the default inspection", () => {
  assert.equal(rowSpecLine({ specs }), "Anodize, Type II, Ra 1.6 µm · Stress relief");
  assert.equal(rowSpecLine({ specs: null }), null);
  assert.equal(rowSpecLine({ specs: { ...specs, summary: ["Inspection: Standard inspection"] } }), null);
});

test("what the supplier must hold shows where the part is bought outside", () => {
  assert.equal(rowMustHold({ bucket: "outside", specs }), "Supplier must hold AS9100, ITAR registration");
  assert.equal(rowMustHold({ bucket: "in_house", specs }), null);
});

test("outcome and sign-off, and when it went out of date", () => {
  assert.equal(rowSignoffLine({ outcome: null }), null);
  assert.deepEqual(rowSignoffLine({ outcome: "outside" }), { text: "Make outside · not signed off", tone: "unk" });
  assert.deepEqual(rowSignoffLine({ outcome: "inhouse", record_out_of_date: true }), { text: "Make in-house · not signed off · record out of date", tone: "warn" });
  const so = { by: "Ada", at: "2026-10-22T10:00:00Z", note: null, stale: false, stale_reason: null };
  assert.deepEqual(rowSignoffLine({ outcome: "inhouse", signoff: so }), { text: "Make in-house · signed off by Ada Oct 22", tone: "ok" });
  assert.deepEqual(rowSignoffLine({ outcome: "inhouse", signoff: { ...so, stale: true, stale_reason: "machine_inventory_changed" } }), { text: "Make in-house · signed off by Ada, now out of date", tone: "warn" });
});

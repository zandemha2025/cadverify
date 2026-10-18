import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { MIN_HELD_OUT, MIN_REAL_RECORDS, bandPos, countRecords, methodRows, parseJob, rangeOf, type GtRecord, type JobForm } from "./actuals-derive.ts";
import type { EstimateRow } from "./shop-api.ts";

const backend = (p: string) => readFileSync(new URL(`../../../../../backend/${p}`, import.meta.url), "utf8");

test("floors match the backend constants", () => {
  assert.equal(Number(/^MIN_REAL_RECORDS = (\d+)$/m.exec(backend("src/services/groundtruth_service.py"))?.[1]), MIN_REAL_RECORDS);
  assert.equal(Number(/^MIN_RESIDUALS = (\d+)$/m.exec(backend("src/costing/groundtruth.py"))?.[1]), MIN_HELD_OUT);
});

const rec = (process: string, stand_in = false): GtRecord => ({ part_id: "a.stl", process, quantity: 10, actual_unit_cost_usd: 30, stand_in, source: "PO-1", created_at: null });

test("stand-ins never count as real records", () => {
  assert.deepEqual(countRecords([rec("cnc_3axis"), rec("cnc_3axis", true), rec("sls")]), { real: 2, standIn: 1 });
  assert.deepEqual(countRecords(null), { real: 0, standIn: 0 });
});

test("method rows: owned methods and logged methods, measured only from real held-out results", () => {
  const machines = [{ process: "cnc_3axis", name: "Haas VF-2" }, { process: "mjf", name: "HP 5200" }];
  const records = [rec("cnc_3axis"), rec("cnc_3axis"), rec("cnc_3axis", true), rec("sls")];
  const base = { machines, records, savedProcesses: ["cnc_3axis", "cnc_3axis", null], estimates: [] as (EstimateRow | null)[] };
  const rows = methodRows({ ...base, recal: null });
  assert.deepEqual(rows.map((r) => [r.process, r.real, r.savedParts, r.heldOut, r.measured]), [
    ["cnc_3axis", 2, 2, null, false],
    ["mjf", 0, 0, null, false],
    ["sls", 1, 0, null, false],
  ]);
  const recal = { n_real: 9, n_records: 10, n_skipped: 0, validated: true, validated_processes: ["cnc_3axis"], claim: "x", heldout_metrics_real: { per_process: { cnc_3axis: { n: 3 } } } };
  const after = methodRows({ ...base, recal });
  assert.deepEqual(after.map((r) => [r.process, r.heldOut, r.measured]), [["cnc_3axis", 3, true], ["mjf", 0, false], ["sls", 0, false]]);
  // Without a recalibration this session, a saved estimate's validated band says so.
  const est = { process: "mjf", confidence: { validated: true, n_samples: 4 } } as EstimateRow;
  assert.deepEqual(methodRows({ ...base, estimates: [est], recal: null })[1], { process: "mjf", machines: ["HP 5200"], savedParts: 0, real: 0, heldOut: 4, measured: true });
});

const form: JobForm = { part: "bored-block-mm.iges", process: "cnc_3axis", quantity: "10", cost: "31.80", material: "aluminum", kind: "invoice", source: "PO-77", date: "2026-10-01", machineH: "1.2", setupH: "", laborH: "0.5", inspectH: "" };

test("log a job: a valid form becomes the API body; blanks stay unknown", () => {
  const r = parseJob(form);
  assert.equal(r.ok, true);
  if (!r.ok) return;
  assert.deepEqual(r.body, {
    part_id: "bored-block-mm.iges", process: "cnc_3axis", quantity: 10, actual_unit_cost_usd: 31.8, material_class: "aluminum",
    source: "PO-77", source_type: "invoice", invoice_date: "2026-10-01",
    actual_machine_hours: 1.2, actual_setup_hours: null, actual_labor_hours: 0.5, actual_inspection_hours: null,
  });
});

test("log a job: malformed values are reported, never coerced", () => {
  const r = parseJob({ ...form, part: " ", quantity: "1.5", cost: "0", date: "2026-02-30", machineH: "1h" });
  assert.equal(r.ok, false);
  if (r.ok) return;
  assert.deepEqual(Object.keys(r.errors).sort(), ["cost", "date", "machineH", "part", "quantity"]);
  assert.equal(r.errors.quantity, "Whole number, 1 or more.");
});

test("a part's range comes from its estimate's band", () => {
  const e = { unit_cost_usd: 31.54, confidence: { low_usd: 15.77, high_usd: 47.31, point_usd: 31.54, half_width_pct: 50, validated: false, n_samples: 0 } } as EstimateRow;
  const r = rangeOf(e)!;
  assert.deepEqual(r, { point: 31.54, low: 15.77, high: 47.31, pct: 50, measured: false, n: 0 });
  assert.equal(Math.round(bandPos(r, r.point)), 50);
  assert.equal(bandPos(r, r.low), 6);
  assert.equal(rangeOf(null), null);
});

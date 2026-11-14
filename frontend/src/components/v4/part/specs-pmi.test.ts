import test from "node:test";
import assert from "node:assert/strict";
import { pmiBlock, pmiHeld, pmiLine, type PmiEntry } from "./specs.ts";

function entry(over: Partial<PmiEntry> = {}): PmiEntry {
  return {
    tolerance_id: "TOL-001",
    tolerance_type: "position",
    value_mm: 0.1,
    process_verdicts: [
      { process: "cnc_3axis", verdict: "achievable", process_capability_mm: 0.05, margin_mm: 0.05 },
      { process: "sheet_metal", verdict: "not_achievable", process_capability_mm: 0.3, margin_mm: -0.2 },
    ],
    ...over,
  };
}

test("a geometric tolerance renders its callout, datums and feature", () => {
  const line = pmiLine(entry({ datum_refs: ["A", "B"], feature_description: "the boss face" }));
  assert.equal(line, "position 0.1 mm · A|B — the boss face");
});

test("a dimensional tolerance renders its deviations, not a zone width", () => {
  const line = pmiLine(entry({ tolerance_type: "diameter", upper_deviation: 0.02, lower_deviation: -0.01 }));
  assert.equal(line, "diameter +0.02 / −0.01 mm");
});

test("an angular size reads in degrees", () => {
  const line = pmiLine(entry({ tolerance_type: "angular_size", value_mm: 1, upper_deviation: 0.5, lower_deviation: -0.5, unit: "deg", feature_description: "60°" }));
  assert.equal(line, "angular_size +0.5 / −0.5° — 60°");
});

test("a one-sided diameter keeps its zero side (NIST CTC-01: 35 +0/-0.2)", () => {
  const line = pmiLine(entry({ tolerance_type: "diameter", value_mm: 0.2, upper_deviation: 0, lower_deviation: -0.2, feature_description: "⌀35 mm", process_verdicts: [] }));
  assert.equal(line, "diameter +0 / −0.2 mm — ⌀35 mm");
});

test("surface finish rides the line it belongs to", () => {
  const line = pmiLine(entry({ surface_finish_ra_um: 1.6 }));
  assert.ok(line.includes("Ra 1.6 µm"), line);
});

test("held counts only the routes that can hold the tolerance", () => {
  assert.equal(pmiHeld(entry()), "1 of 2 routes hold it");
  assert.equal(pmiHeld(entry({ process_verdicts: undefined })), null);
});

test("pmiBlock is null without a report, honest with one that has no PMI", () => {
  assert.equal(pmiBlock(null), null);
  assert.equal(pmiBlock(undefined), null);
  const none = pmiBlock({ has_pmi: false, pmi_note: "No GD&T annotations found in STEP file; analysis based on geometry only." });
  assert.deepEqual(none, { lines: [], held: [], note: "No GD&T annotations found in STEP file; analysis based on geometry only." });
});

test("pmiBlock keeps every entry and its held-by line in step", () => {
  const b = pmiBlock({ has_pmi: true, entries: [entry(), entry({ tolerance_id: "TOL-002", tolerance_type: "flatness", value_mm: 0.05, process_verdicts: [] })] });
  assert.equal(b!.lines.length, 2);
  assert.equal(b!.held[0], "1 of 2 routes hold it");
  assert.equal(b!.held[1], null);
});

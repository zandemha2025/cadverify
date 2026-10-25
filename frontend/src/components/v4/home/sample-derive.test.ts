/** Sample result summary from a real-shaped run. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { sampleBarLine, sampleSummary, type SampleRunLite } from "./sample-derive.ts";

const RUN: SampleRunLite = {
  file: { name: "sample-routing-bracket.stl" },
  validation: {
    geometry: { bounding_box_mm: [50, 40, 6], volume_mm3: 5950, faces: 20, is_watertight: true },
    process_scores: [
      { process: "fdm", verdict: "issues", score: 0.8, issues: [{ code: "ASPECT_RATIO", severity: "warning", message: "Aspect ratio 8.3 : 1 is over the 8 : 1 limit.", fix_suggestion: "Split it, brace it or reorient it." }] },
      { process: "sheet_metal", verdict: "pass", score: 0.9, issues: [] },
      { process: "cnc_turning", verdict: "fail", score: 0, issues: [{ code: "NOT_ROTATIONALLY_SYMMETRIC", severity: "error", message: "x" }] },
      { process: "injection_molding", verdict: "fail", score: 0, issues: [{ code: "WALL_THICKNESS_PRECISION", severity: "warning", message: "" }, { code: "INSUFFICIENT_DRAFT", severity: "error", message: "x" }] },
      { process: "die_casting", verdict: "fail", score: 0, issues: [{ code: "INSUFFICIENT_DRAFT", severity: "error", message: "x" }] },
    ],
  },
  cost: {
    saved: { id: "01X" },
    decision: { recommendation: { "1": { process: "fdm", material: "PLA", unit_cost_usd: 30 }, "10": { process: "sheet_metal", material: "5052 Aluminum", unit_cost_usd: 7.5 }, "100": { process: "sheet_metal", material: "5052 Aluminum", unit_cost_usd: 3 } } },
    assumptions: [{ provenance: "DEFAULT" }],
  },
  verification: { verdict: "makeable_in_house", best_machine: "HP Jet Fusion 5200" },
};

test("sample summary reads the run", () => {
  const s = sampleSummary(RUN);
  assert.deepEqual(s.figs.map((f) => `${f.k}|${f.v}|${f.s}`), [
    "Can make it|2 of 5|3 can't as drawn",
    "Make now · 1|$30.00|Filament printing (FDM/FFF) · PLA",
    "Each at 10|$7.50|Sheet metal · 5052 Aluminum",
    "Your shop|In-house|HP Jet Fusion 5200",
  ]);
  assert.deepEqual(s.firstIssue, { way: "Filament printing (FDM/FFF)", tone: "warn", chip: "Warning", text: "Aspect ratio 8.3 : 1 is over the 8 : 1 limit. Split it, brace it or reorient it." });
  assert.equal(s.cantText, "Turning: not a round part. Injection molding, Die casting: no draft on the straight walls.");
  assert.deepEqual(s.measured, [["Size", "50 × 40 × 6 mm"], ["Volume", "5.95 cm³"], ["Faces", "20"], ["Watertight", "Yes"]]);
  assert.equal(s.ratesNote, "Costs use typical rates, not supplier quotes.");
  assert.equal(sampleBarLine(s), "sample-routing-bracket.stl · 2 of 5 can make it · saved to Records");
});

test("no cost and no machine verdict: figures left out, shop not checked", () => {
  const s = sampleSummary({ ...RUN, cost: null, verification: null });
  assert.deepEqual(s.figs.map((f) => f.k), ["Can make it", "Your shop"]);
  assert.equal(s.figs[1].v, "Not checked");
  assert.equal(s.firstIssue, null);
  assert.equal(s.saved, false);
});

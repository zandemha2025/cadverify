// Regression: QA-001 — Glass Box, Inspector and saved scenarios used different routes.
// Found by /qa on 2026-10-08
// Report: .gstack/qa-reports/qa-report-scalecad-ai-2026-10-08.md
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { workspaceSelection, pickEstimate } from "./cost-views.ts";
import { captureCostScenario } from "./cost-scenario.ts";
import type { CostReport, CostOptions } from "./api.ts";

const report = {
  quantities: [50, 5000], material_class: "polymer", status: "OK",
  decision: { make_now_process: "mjf", make_now_material: "PA12", crossover_qty: null },
  estimates: [
    { process: "mjf", material: "PA12", quantity: 50, unit_cost_usd: 3.80, dfm_ready: true, drivers: [{ name: "material_cost", value: 1 }] },
    { process: "mjf", material: "PA12", quantity: 5000, unit_cost_usd: 2, dfm_ready: true, drivers: [] },
    { process: "cnc_3axis", material: "ABS", quantity: 50, unit_cost_usd: 30, dfm_ready: true, drivers: [] },
    { process: "cnc_3axis", material: "ABS", quantity: 5000, unit_cost_usd: 11.76, dfm_ready: true, drivers: [{ name: "machine_cost", value: 8 }] },
    { process: "excluded", material: "ABS", quantity: 5000, unit_cost_usd: .01, environment_excluded: true },
  ],
} as unknown as CostReport;
const options: CostOptions = { qty: "50,5000", region: "US", units: "mm", cavities: 1,
  complexity: "moderate", material_class: "polymer", overrides: { labor_rate: 70 } };

test("CNC at 5,000 supplies the same price and driver row to Inspector and scenario capture/recall", () => {
  const glassBoxRow = pickEstimate(report, "cnc_3axis", 5000)!;
  const selected = workspaceSelection(report, null, undefined, glassBoxRow);
  assert.equal(selected.quantity, 5000);
  assert.equal(selected.recommendation?.unitCost, 11.76);
  assert.equal(selected.estimate, glassBoxRow);
  assert.equal(selected.estimate?.drivers[0].name, "machine_cost");
  assert.equal(selected.dfm.process, "cnc_3axis");
  const saved = captureCostScenario(selected, options)!;
  assert.match(saved.label, /qty 5,000/);
  assert.equal(saved.process, "cnc_3axis");
  assert.equal(saved.unitCost, 11.76);
  assert.equal(saved.opts.qty, "50,5000");
  const recosted = structuredClone(report);
  recosted.estimates.find((e) => e.process === "cnc_3axis" && e.quantity === 5000)!.unit_cost_usd = 12.50;
  const recalled = workspaceSelection(recosted, null, undefined, saved.route);
  assert.equal(recalled.quantity, 5000);
  assert.equal(recalled.estimate?.process, "cnc_3axis");
  assert.equal(recalled.recommendation?.unitCost, 12.50, "recall uses fresh engine prices");
  options.overrides!.labor_rate = 35;
  assert.equal(saved.opts.overrides?.labor_rate, 70, "draft edits cannot mutate the saved inputs");
});

test("continuous quantities remain approximate on recall and stale/excluded routes cannot borrow evidence", () => {
  const selection = workspaceSelection(report, null, undefined, { process: "cnc_3axis", material: "ABS", quantity: 1000 });
  const saved = captureCostScenario(selection, options)!;
  assert.match(saved.label, /qty 1,000 · approx\./);
  const recalled = workspaceSelection(structuredClone(report), null, undefined, saved.route);
  assert.equal(recalled.quantity, 1000);
  assert.equal(recalled.recommendation?.unitCost, saved.unitCost);
  assert.notEqual(recalled.estimate?.quantity, 1000, "no fabricated exact drivers");
  for (const route of [
    { process: "excluded", material: "ABS", quantity: 5000 },
    { process: "cnc_3axis", material: "missing", quantity: 5000 },
    { process: "cnc_3axis", material: "ABS", quantity: NaN },
  ]) assert.equal(workspaceSelection(report, null, undefined, route).selectedRoute, false);
  assert.equal(captureCostScenario(workspaceSelection(null, null), options), null);
});

test("both workspace layouts wire Glass Box choices to their resident shared selection", () => {
  for (const file of ["PartWorkspace.tsx", "hero/PartHero.tsx"]) {
    const source = readFileSync(new URL(`../components/workspace/${file}`, import.meta.url), "utf8");
    assert.match(source, /<GlassBoxView\s+report=\{report\}\s+selection=\{selection\}\s+onSelectRoute=\{onSelectRoute\}/);
  }
  const workspace = readFileSync(new URL("../components/workspace/PartWorkspace.tsx", import.meta.url), "utf8");
  assert.match(workspace, /captureCostScenario\(selection, reportOptions/);
  assert.match(workspace, /recostWith\(scn\.opts, scn\.route\)/);
});

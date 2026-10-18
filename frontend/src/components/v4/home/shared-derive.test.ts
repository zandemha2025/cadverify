/** Shared link derivations: hidden shop inputs stay hidden; ways and figures from the payload. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { assumptionName, assumptionSource, assumptionValue, checkFacts, checkWays, crossoverLine, listQty, pickRange, priceFigs, wayRows, type SharedCostLite } from "./shared-derive.ts";

const HIDDEN = "Set by the sharer's shop. Not shown on shared links.";

test("assumptions: hidden values render as Hidden; units read plainly", () => {
  assert.equal(assumptionValue({ name: "machine_rate", value: null, unit: "$/hr", provenance: "SHOP", source: HIDDEN }), "Hidden");
  assert.equal(assumptionValue({ name: "labor_rate", value: 35, unit: "$/hr", provenance: "DEFAULT", source: "x" }), "$35/h");
  assert.equal(assumptionValue({ name: "margin", value: 0, unit: "frac", provenance: "DEFAULT", source: "x" }), "none added");
  assert.equal(assumptionValue({ name: "perishable_frac", value: 0.05, unit: "frac", provenance: "DEFAULT", source: "x" }), "5%");
  assert.equal(assumptionValue({ name: "stock_allowance", value: 1.1, unit: "×", provenance: "DEFAULT", source: "x" }), "×1.1");
  assert.equal(assumptionValue({ name: "material_class", value: 0, unit: "aluminum", provenance: "USER", source: "x" }), "aluminum");
  assert.equal(assumptionName("labor_rate"), "Labor");
  assert.equal(assumptionName("some_new_input"), "Some new input");
  assert.deepEqual(assumptionSource({ name: "a", value: 1, unit: "", provenance: "USER", source: "" }), { kind: "yours", label: "Sharer's" });
  assert.equal(assumptionSource({ name: "a", value: 1, unit: "", provenance: "DEFAULT", source: "" }).label, "Typical");
});

const COST: SharedCostLite = {
  filename: "disk.step",
  label: null,
  created_at: "2026-10-18T04:16:00Z",
  quantities: [10, 100],
  geometry: { bbox_mm: [220, 220, 8], volume_cm3: 304.1 },
  material_class: "aluminum",
  estimates: [
    { process: "cnc_3axis", material: "6061-T6 Aluminum", quantity: 10, unit_cost_usd: 118.74, dfm_ready: true, lead_time: { low_days: 7, high_days: 13 }, confidence: { low_usd: 59.37, high_usd: 178.11, half_width_pct: 50, validated: false } },
    { process: "sand_casting", material: "A356 Aluminum", quantity: 10, unit_cost_usd: 1083.86, dfm_ready: false, dfm_blockers: ["5460 sidewall faces (100.0% of sidewall area) below 3.0° draft for sand_casting."], lead_time: { low_days: 19.6, high_days: 36.4 } },
    { process: "cnc_3axis", material: "6061-T6 Aluminum", quantity: 100, unit_cost_usd: 108.5, dfm_ready: true },
  ],
  decision: { recommendation: { "10": { process: "cnc_3axis", material: "6061-T6 Aluminum", unit_cost_usd: 118.74 }, "100": { process: "cnc_3axis", material: "6061-T6 Aluminum", unit_cost_usd: 108.5 } }, crossover_qty: 146, tooling_process: "sand_casting", tooling_dfm_ready: false },
  assumptions: [],
};

test("prices, ways, range and crossover come from the payload", () => {
  assert.deepEqual(priceFigs(COST), [
    { k: "At 10", v: "$118.74", s: "3-axis milling" },
    { k: "At 100", v: "$108.50", s: "3-axis milling" },
  ]);
  assert.equal(listQty(COST), 10);
  const w = wayRows(COST, 10);
  assert.equal(w.length, 2);
  assert.equal(w[0].name, "3-axis milling · 6061-T6 Aluminum");
  assert.equal(w[0].note, "7–13 days");
  assert.equal(w[1].note, "Only after a design change: 5460 sidewall faces below 3.0° draft · 20–36 days");
  assert.equal(pickRange(COST, 10), "3-axis milling at 10: $59.37–$178.11 (±50%, no real costs yet)");
  assert.equal(crossoverLine(COST), "Sand casting costs less from about 146 parts, after a design change");
});

test("shared check: can-make ways first by score, then can't; facts", () => {
  const d = {
    filename: "b.iges",
    created_at: "2026-10-18T03:39:00Z",
    face_count: 10,
    best_process: "dlp",
    geometry: null,
    universal_issues: [],
    process_scores: [
      { process: "cnc_turning", score: 0.2, verdict: "fail", issues: [{ code: "WALL_THICKNESS_PRECISION", severity: "warning", message: "" }, { code: "NOT_ROTATIONALLY_SYMMETRIC", severity: "error", message: "" }] },
      { process: "fdm", score: 0.9, verdict: "issues", issues: [{ code: "WALL_THICKNESS_PRECISION", severity: "warning", message: "" }] },
      { process: "dlp", score: 1, verdict: "pass", issues: [] },
    ],
  };
  const w = checkWays(d);
  assert.deepEqual(w.map((x) => `${x.name}:${x.verdict}:${x.count}`), ["Resin printing, DLP:Can make:0 findings", "Filament printing:Check:1 finding", "Lathe:Can't:2 findings"]);
  assert.deepEqual(w[2].findings, ["Not a round part (must change)", "Walls near the limit, unconfirmed (advisory)"]);
  assert.deepEqual(checkFacts(d), { can: 2, cant: 1, total: 3 });
});

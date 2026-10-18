import assert from "node:assert/strict";
import test from "node:test";

import {
  costLines,
  countInputs,
  headlineEstimate,
  headlineQty,
  previewAt,
  provOf,
  regionsFromAssumptions,
  regionsFromPayload,
  rowsFromAssumptions,
  rowsFromPayload,
} from "./rates-derive.ts";
import type { Assumption, EstimateRow, RecordDetail } from "./shop-api.ts";

// Shapes copied from a saved staging record (bored block, 3-axis milling, qty 1).
const assumptions: Assumption[] = [
  { name: "labor_rate", value: 35, unit: "$/hr", provenance: "DEFAULT", source: "loaded shop-floor labor" },
  { name: "region_labor", value: 1, unit: "×", provenance: "DEFAULT", source: "region US: labor/machine/setup ×1" },
  { name: "region_material", value: 1, unit: "×", provenance: "DEFAULT", source: "region US: commodity material ×1" },
  { name: "region_tooling", value: 1, unit: "×", provenance: "DEFAULT", source: "region US: tooling ×1" },
  { name: "margin", value: 0, unit: "frac", provenance: "DEFAULT", source: "markup" },
  { name: "overhead", value: 0, unit: "frac", provenance: "USER", source: "set for this quote" },
  { name: "utilization", value: 1, unit: "frac", provenance: "DEFAULT", source: "" },
  { name: "stock_allowance", value: 1.1, unit: "×", provenance: "DEFAULT", source: "" },
  { name: "daily_machine_hours", value: 8, unit: "hr/day", provenance: "DEFAULT", source: "" },
];

const est = (over: Partial<EstimateRow> = {}): EstimateRow => ({
  process: "cnc_3axis",
  material: "PEEK",
  quantity: 10,
  unit_cost_usd: 30.61,
  confidence: { validated: false, method: "assumption-band" },
  drivers: [
    { name: "material_cost", unit: "$", value: 0.45, provenance: "DEFAULT", source: "billet × $100/kg" },
    { name: "machine_cost", unit: "$", value: 2.0, provenance: "USER", source: "0.0241 hr × $85/hr (fitted machine 'Haas VF-2', its OWN declared rate)" },
    { name: "cycle_time", unit: "hr", value: 0.0241, provenance: "DEFAULT", source: "rough" },
    { name: "labor_cost", unit: "$", value: 17.5, provenance: "DEFAULT", source: "post-process 0.5 hr × $35/hr × region-labor ×1" },
    { name: "setup_cost", unit: "$", value: 2.625, provenance: "DEFAULT", source: "setup 0.75hr × $35/hr × ceil(10/100) = 1 setups ÷ 10" },
    { name: "nre_cost", unit: "$", value: 7, provenance: "DEFAULT", source: "CAM programming/NRE 2hr × $35/hr × region-labor ×1 ÷ 10 order" },
    { name: "inspection_cost", unit: "$", value: 1.0, provenance: "DEFAULT", source: "0.03hr/part = 0.0800hr × $35/hr" },
    { name: "consumables_cost", unit: "$", value: 0.035, provenance: "DEFAULT", source: "perishable 0.05 × machine $0.70" },
  ],
  ...over,
});

test("provenance words: yours, your file, typical", () => {
  assert.equal(provOf("USER"), "yours");
  assert.equal(provOf("SHOP"), "yours");
  assert.equal(provOf("CAD"), "file");
  assert.equal(provOf("MEASURED"), "file");
  assert.equal(provOf("DEFAULT"), "typ");
});

test("v0 rows come only from defaults a check recorded; a user override is not the card", () => {
  const rows = rowsFromAssumptions(assumptions);
  assert.deepEqual(rows.map((r) => [r.key, r.value]), [
    ["labor_rate", "$35.00/h"],
    ["margin", "0%"],
    ["utilization", "100%"],
    ["stock_allowance", "1.10×"],
    ["daily_machine_hours", "8"],
  ]);
  assert.deepEqual(rowsFromAssumptions(null), []);
});

test("governed rows read the card's table; missing keys are left out", () => {
  const rows = rowsFromPayload({ global: { labor_rate: 42.5, margin: 0.25, machine_capital_frac: 0.35, ship_days: 3 } });
  assert.deepEqual(rows.map((r) => r.value), ["$42.50/h", "25%", "35%", "3 days"]);
  assert.deepEqual(rowsFromPayload(null), []);
});

test("regional multipliers: all six from a card, only used regions from checks", () => {
  const card = regionsFromPayload({ region_labor: { US: 1, CN: 0.55 }, region_material: { US: 1 }, region_tooling: { US: 1, CN: 0.45 } });
  assert.equal(card.length, 6);
  assert.deepEqual(card.find((r) => r.code === "CN"), { code: "CN", name: "China", labor: "×0.55", material: "—", tooling: "×0.45" });
  const used = regionsFromAssumptions([assumptions, assumptions, null]);
  assert.deepEqual(used, [{ code: "US", name: "United States", labor: "×1.00", material: "×1.00", tooling: "×1.00" }]);
});

test("headline estimate is the decision's pick at 10, else the first quantity", () => {
  assert.equal(headlineQty([1, 10, 100]), 10);
  assert.equal(headlineQty([5, 50]), 5);
  assert.equal(headlineQty([]), null);
  const d = {
    id: "r", filename: "p.step", label: null, make_now_process: "fdm", created_at: "", quantities: [1, 10],
    result: {
      estimates: [est({ process: "fdm", material: "PLA", quantity: 10 }), est({ quantity: 10 }), est({ quantity: 1 })],
      decision: { make_now_process: "fdm", recommendation: { "10": { process: "cnc_3axis", material: "PEEK", unit_cost_usd: 30.61 } } },
    },
  } as RecordDetail;
  const h = headlineEstimate(d);
  assert.equal(h?.process, "cnc_3axis");
  assert.equal(h?.quantity, 10);
});

test("only labor-paid lines at the recorded labor rate scale", () => {
  const lines = costLines(est(), 35);
  assert.deepEqual(lines.filter((l) => l.scales).map((l) => l.key), ["labor_cost", "setup_cost", "nre_cost", "inspection_cost"]);
  assert.equal(lines.find((l) => l.key === "machine_cost")?.name, "Machine, at your $85/h");
  assert.equal(lines.find((l) => l.key === "labor_cost")?.name, "Labor, finishing, 0.5 h");
  assert.ok(!lines.some((l) => l.key === "cycle_time"));
  // A machine billed at $35/hr never reads as labor.
  const odd = costLines(est({ drivers: [{ name: "machine_cost", unit: "$", value: 1, provenance: "DEFAULT", source: "1 hr × $35/hr" }] }), 35);
  assert.equal(odd[0].scales, false);
});

test("preview: cost each moves by the labor lines; withheld when a floor applies", () => {
  const p = previewAt(est(), 35, 45);
  assert.equal(p.scaling, 4);
  assert.ok(Math.abs(p.delta - (17.5 + 2.625 + 7 + 1.0) * (10 / 35)) < 1e-9);
  assert.ok(p.total != null && Math.abs(p.total - (30.61 + p.delta)) < 1e-9);
  assert.equal(previewAt(est(), 35, 35).delta, 0);
  const floored = est({ drivers: [...est().drivers, { name: "min_charge_floor", unit: "$", value: 30, provenance: "DEFAULT", source: "shop minimum $300/lot ÷ 10 = $30.00/unit floor (applied)" }] });
  assert.equal(previewAt(floored, 35, 45).total, null);
  assert.equal(previewAt(est(), 35, 45, { margin: 0.25 }).total, null);
});

test("cost inputs are counted per part by where they come from", () => {
  const c = countInputs([est(), null, est({ confidence: { validated: true } })]);
  assert.deepEqual(c, { parts: 2, total: 14, yours: 2, file: 0, typ: 12, measured: 7 });
});

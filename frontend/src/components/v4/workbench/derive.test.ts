/**
 * Cost breakdown derivations: option validation and round trips, the log quantity
 * scale, the decision at a quantity, the chart, findings and the methods
 * matrix, compare tables, history rows and the copied summary.
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/components/v4/workbench/derive.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import type { CostEstimate, CostReport, ValidationResult } from "@/lib/api";
import { deriveBreakeven } from "../../../lib/breakeven.ts";
import {
  DEFAULT_FORM,
  QTY_RULE,
  blockerSentence,
  cavProblem,
  changeText,
  chartModel,
  compareByQty,
  compareByRates,
  costsAt,
  crossText,
  decadeTicks,
  decisionAt,
  decisionSummary,
  defaultQty,
  driverValue,
  findingRows,
  formToOptions,
  governance,
  historyRows,
  methodMatrix,
  methodsAt,
  nearestQty,
  optionsFromReport,
  optionsToForm,
  posToQ,
  qToPos,
  qtyProblem,
  rateChips,
  redesignNote,
  sameForm,
  scaleMax,
  scenarioLabel,
  threeSource,
  sumCheck,
} from "./derive.ts";
import { assumptionValue, environmentLabel, findingTitle, qtyListText, shortSource } from "./words.ts";

function est(process: string, quantity: number, unit: number, extra: Partial<CostEstimate> = {}): CostEstimate {
  return {
    process,
    material: process === "wire_edm" ? "API 13Cr" : "SS316L",
    quantity,
    unit_cost_usd: unit,
    fixed_cost_usd: 0,
    variable_cost_usd: unit,
    est_error_band_pct: 50,
    dfm_ready: true,
    dfm_verdict: "issues",
    dfm_score: 0.9,
    dfm_blockers: [],
    line_items: { material: unit * 0.25, machine: unit * 0.75 },
    drivers: [
      { name: "material_cost", value: unit * 0.25, unit: "$", provenance: "DEFAULT", source: "billet × $7/kg", error_band_pct: 5 },
      { name: "machine_cost", value: unit * 0.75, unit: "$", provenance: "SHOP", source: "0.5 hr × $85/hr", error_band_pct: 50 },
    ],
    lead_time: { low_days: 7.7, high_days: 14.3, mid_days: 11, components: {}, capacity: {} },
    ...extra,
  };
}

function report(extra: Partial<CostReport> = {}): CostReport {
  return {
    filename: "bored-block-mm.iges",
    status: "OK",
    reason: null,
    geometry: { volume_cm3: 2.72, surface_area_cm2: 14.3, bbox_mm: [20, 15, 10], watertight: true, face_count: 185386 },
    material_class: "stainless",
    quantities: [1, 10, 100],
    estimates: [
      est("wire_edm", 1, 110, { confidence: { low_usd: 60.5, high_usd: 159.5, point_usd: 110, level: 0.8, method: "assumption-band", validated: false, n_samples: 0, half_width_pct: 45, basis: "±45%", label: "assumption-based, not yet validated" } }),
      est("wire_edm", 10, 16.16),
      est("wire_edm", 100, 14.06),
      est("binder_jetting", 1, 150),
      est("binder_jetting", 10, 15),
      est("binder_jetting", 100, 3.54),
      est("forging", 1, 12121.85, { dfm_ready: false, dfm_blockers: ["114852 sidewall faces (100.0% of sidewall area) below 5.0° draft for forging."] }),
      est("forging", 10, 1227.35, { dfm_ready: false }),
      est("forging", 100, 137.9, { dfm_ready: false }),
    ],
    engine_feasibility: [],
    notes: [],
    assumptions: [
      { name: "labor_rate", value: 52, unit: "$/hr", provenance: "SHOP", source: "loaded shop-floor labor [shop: Midwest Precision CNC]" },
      { name: "margin", value: 0.3, unit: "frac", provenance: "SHOP", source: "markup" },
      { name: "stock_allowance", value: 1.1, unit: "×", provenance: "DEFAULT", source: "CNC stock" },
      { name: "region_labor", value: 1, unit: "×", provenance: "DEFAULT", source: "region MX: labor/machine/setup ×0.7" },
      { name: "n_cavities", value: 2, unit: "cav", provenance: "USER", source: "cavities" },
      { name: "complexity", value: 0, unit: "complex", provenance: "USER", source: "complexity" },
    ],
    decision: {
      make_now_process: "wire_edm",
      make_now_material: "API 13Cr",
      tooling_process: "forging",
      tooling_dfm_ready: false,
      crossover_qty: null,
      recommendation: {
        "1": { process: "wire_edm", material: "API 13Cr", unit_cost_usd: 110, dfm_ready: true, dfm_verdict: "issues", lead_low_days: 7.7, lead_high_days: 14.3 },
        "10": { process: "binder_jetting", material: "SS316L", unit_cost_usd: 15, dfm_ready: true, dfm_verdict: "issues", lead_low_days: 10.5, lead_high_days: 19.5 },
        "100": { process: "binder_jetting", material: "SS316L", unit_cost_usd: 3.54, dfm_ready: true, dfm_verdict: "issues", lead_low_days: 10.5, lead_high_days: 19.5 },
      },
      if_redesigned: {},
      note: "",
    },
    ...extra,
  };
}

const issue = (code: string, severity: "error" | "warning" | "info", faces: number[] = [], extra = {}) => ({
  code, severity, message: `${code} message.`, fix_suggestion: null, affected_faces_sample: faces, ...extra,
});

function validation(): ValidationResult {
  return {
    filename: "bored-block-mm.iges",
    file_type: "iges",
    overall_verdict: "issues",
    best_process: "dlp",
    analysis_time_ms: 10,
    geometry: { vertices: 3, faces: 1, volume_mm3: 2717, surface_area_mm2: 1432, bounding_box_mm: [20, 15, 10], is_watertight: true, is_manifold: true, center_of_mass: [0, 0, 0], units: "mm" },
    segments: [],
    universal_issues: [],
    priority_fixes: [],
    process_scores: [
      { process: "wire_edm", score: 0.9, verdict: "issues", recommended_material: null, recommended_machine: null, estimated_cost_factor: null, issues: [issue("CONDUCTIVITY_REQUIRED", "info")] },
      { process: "cnc_3axis", score: 0.8, verdict: "issues", recommended_material: null, recommended_machine: null, estimated_cost_factor: null, issues: [issue("SETUP_ACCESS_UNVERIFIED", "warning", [1, 2])] },
      { process: "forging", score: 0, verdict: "fail", recommended_material: null, recommended_machine: null, estimated_cost_factor: null, issues: [issue("INSUFFICIENT_DRAFT", "error", [3, 4]), issue("SETUP_ACCESS_UNVERIFIED", "warning", [1, 2])] },
      { process: "binder_jetting", score: 0.9, verdict: "issues", recommended_material: null, recommended_machine: null, estimated_cost_factor: null, issues: [] },
    ],
  };
}

test("quantity and cavity rules match the server", () => {
  assert.equal(qtyProblem("50, 5000"), null);
  assert.equal(qtyProblem("1,2,3,4,5,6"), null);
  assert.equal(qtyProblem("1,2,3,4,5,6,7"), QTY_RULE);
  assert.equal(qtyProblem(""), QTY_RULE);
  assert.equal(qtyProblem("0"), QTY_RULE);
  assert.equal(qtyProblem("10000001"), QTY_RULE);
  assert.equal(qtyProblem("2.5"), QTY_RULE);
  assert.equal(cavProblem("1"), null);
  assert.equal(cavProblem(""), "Enter a whole number, 1 or more.");
  assert.equal(cavProblem("0"), "Enter a whole number, 1 or more.");
  assert.equal(cavProblem("1.5"), "Enter a whole number, 1 or more.");
});

test("form round trip keeps the shop and overrides; sameForm ignores spacing", () => {
  const opts = formToOptions({ ...DEFAULT_FORM, qty: " 50 ,5000 ", cav: "3" }, { shop: "midwest", overrides: { labor_rate: 40 } });
  assert.equal(opts.qty, "50,5000");
  assert.equal(opts.cavities, 3);
  assert.equal(opts.shop, "midwest");
  assert.deepEqual(opts.overrides, { labor_rate: 40 });
  assert.ok(sameForm(optionsToForm(opts), { ...DEFAULT_FORM, qty: "50,5000", cav: "3" }));
  assert.ok(!sameForm(optionsToForm(opts), { ...DEFAULT_FORM, qty: "50,5000", cav: "2" }));
});

test("options read back off a saved report", () => {
  const o = optionsFromReport(report({ notes: ["Calibrated to shop 'Midwest Precision CNC' (region US): 19 rate(s). Source: export."] }), [
    { id: "midwest-precision-cnc", name: "Midwest Precision CNC", region: "US", source: null },
  ]);
  assert.equal(o.qty, "1,10,100");
  assert.equal(o.material_class, "stainless");
  assert.equal(o.complexity, "complex");
  assert.equal(o.cavities, 2);
  assert.equal(o.shop, "midwest-precision-cnc");
  assert.equal(o.region, "auto");
  const noShop = optionsFromReport(report(), []);
  assert.equal(noShop.region, "MX");
  assert.equal(noShop.shop, null);
});

test("log quantity scale runs 1 to a whole decade and round-trips", () => {
  const be = deriveBreakeven(report())!;
  assert.equal(scaleMax(be), 10000);
  assert.equal(posToQ(0, 10000), 1);
  assert.equal(posToQ(250, 10000), 10);
  assert.equal(posToQ(1000, 10000), 10000);
  assert.equal(posToQ(qToPos(100, 10000), 10000), 100);
  assert.deepEqual(decadeTicks(10000), [1, 10, 100, 1000, 10000]);
  assert.equal(nearestQty([1, 10, 100], 40), 100);
  assert.equal(nearestQty([1, 10, 100], 25), 10);
  assert.equal(defaultQty(report()), 100);
  assert.equal(defaultQty(report({ decision: { ...report().decision!, crossover_qty: 4018.4 } })), 4018);
});

test("the decision at a quantity: cheapest ready method, engine range when costed", () => {
  const r = report();
  const be = deriveBreakeven(r)!;
  const at1 = decisionAt(r, be, 1)!;
  assert.equal(at1.curve.process, "wire_edm");
  assert.equal(at1.exact, true);
  assert.equal(at1.lo, 60.5);
  assert.equal(at1.hi, 159.5);
  assert.equal(at1.band, 45);
  const at40 = decisionAt(r, be, 40)!;
  assert.equal(at40.exact, false);
  assert.equal(at40.curve.process, "binder_jetting");
  assert.ok(Math.abs(at40.lo! - at40.unit * 0.5) < 1e-9);
  const rows = costsAt(be, 10);
  assert.equal(rows[0].process, "binder_jetting");
  assert.equal(rows[0].tag, "Pick");
  assert.equal(rows.find((x) => x.process === "forging")?.tag, "Redesign");
  assert.equal(crossText(r), "No tooling crossover");
  assert.equal(crossText(report({ decision: { ...r.decision!, crossover_qty: 4018 } })), "Tooling pays off near 4,018");
});

test("redesign note puts the draft blocker in plain words", () => {
  const n = redesignNote(report())!;
  assert.equal(n.title, "Forging needs a design change first");
  assert.equal(n.text, "Every sidewall is under 5° draft (114,852 faces). Its cost is for a redesigned part, not a quote.");
  assert.equal(blockerSentence("12 sidewall faces (40.5% of sidewall area) below 1.0° draft"), "40.5% of the sidewall area is under 1° draft (12 faces).");
  assert.equal(blockerSentence("Part lacks rotation."), "Part lacks rotation.");
  assert.equal(redesignNote(report({ decision: { ...report().decision!, tooling_dfm_ready: true } })), null);
});

test("chart spans the curves' decades and names the redesign-only methods", () => {
  const be = deriveBreakeven(report())!;
  const c = chartModel(be, 10, "binder_jetting", 10000);
  assert.equal(c.xTicks.length, 5);
  assert.equal(c.xTicks[0].label, "1");
  assert.equal(c.xTicks[4].label, "10,000");
  assert.ok(c.yTicks.length >= 2 && c.yTicks.length <= 7);
  assert.deepEqual(c.notReadyNames, ["Forging"]);
  assert.ok(c.rec.startsWith("M56.0"));
  assert.match(c.aria, /At 10: Metal binder jetting \$15\.00\./);
});

test("findings: required fixes first, processes attached, duplicates merged", () => {
  const rows = findingRows(validation());
  assert.deepEqual(rows.map((r) => r.issue.code), ["INSUFFICIENT_DRAFT", "SETUP_ACCESS_UNVERIFIED", "CONDUCTIVITY_REQUIRED"]);
  const access = rows[1];
  assert.deepEqual(access.processes, ["cnc_3axis", "forging"]);
  assert.equal(access.localized, true);
  assert.equal(access.kind, "reach");
  assert.equal(rows[0].kind, "draft");
  assert.equal(rows[2].localized, false);
  assert.equal(rows[2].kind, "none");
  assert.equal(rows[0].title, "Sidewalls have no draft");
  assert.equal(findingTitle("WALL_UNIFORMITY_SAMPLED", 7.79, "mm"), "Thickest section 7.79 mm");
  assert.equal(findingTitle("SOMETHING_NEW", null, null, "Short engine sentence. More."), "Short engine sentence");
});

test("findings worded per method merge into one row with each method's own need", () => {
  const v = validation();
  v.process_scores.push({
    process: "injection_molding", score: 0, verdict: "fail", recommended_material: null, recommended_machine: null, estimated_cost_factor: null,
    issues: [issue("INSUFFICIENT_DRAFT", "error", [3, 4], { message: "Draft below 1° for injection_molding.", required_value: 1, measurement_unit: "deg" })],
  });
  v.process_scores[2].issues[0] = issue("INSUFFICIENT_DRAFT", "error", [3, 4], { message: "Draft below 5° for forging.", required_value: 5, measurement_unit: "deg" });
  const rows = findingRows(v);
  const draft = rows.filter((r) => r.issue.code === "INSUFFICIENT_DRAFT");
  assert.equal(draft.length, 1);
  assert.deepEqual(draft[0].processes, ["forging", "injection_molding"]);
  assert.deepEqual(draft[0].needs.map((n) => [n.process, n.issue.required_value]), [["forging", 5], ["injection_molding", 1]]);
  assert.equal(draft[0].members.length, 2);
});

test("methods matrix: fit, first blocker, cost at the nearest costed quantity", () => {
  const v = validation();
  const r = report({ routing: { archetype: "prismatic_block", recommended_process: "cnc_3axis", eval_family: "", material_hint: "", confidence: 0.6, reasoning: "", alternatives: [], drivers: {} } });
  const m = methodMatrix(v, r, 12, findingRows(v));
  assert.equal(m.qty, 10);
  assert.equal(m.costPick, "binder_jetting");
  assert.equal(m.geoPick, "cnc_3axis");
  assert.equal(m.cantAsDrawn, 1);
  assert.equal(m.rows[m.rows.length - 1].process, "forging");
  const forging = m.rows.find((x) => x.process === "forging")!;
  assert.equal(forging.first?.title, "Sidewalls have no draft");
  assert.ok(forging.first?.key);
  assert.equal(forging.cost, 1227.35);
  const mill = m.rows.find((x) => x.process === "cnc_3axis")!;
  assert.equal(mill.cost, null);
  assert.equal(mill.note, "Geometry pick · 1 finding");
  assert.equal(m.rows.find((x) => x.process === "binder_jetting")!.note, "Cost pick at 10 · 0 findings");
  assert.equal(m.foot, "Cheapest at 10 is metal binder jetting. The geometry reads as 3-axis milling. Pick on intent, not only price.");
});

test("glass box pieces: methods at a quantity, sum check, governance, rate chips", () => {
  const r = report();
  const ms = methodsAt(r, 10);
  assert.deepEqual(ms.map((m) => m.process), ["binder_jetting", "wire_edm", "forging"]);
  const e = r.estimates[0];
  assert.ok(sumCheck(e).coherent);
  assert.ok(!sumCheck({ ...e, line_items: { material: 1 } }).coherent);
  const g = governance(e.drivers);
  assert.equal(g.grounded, 1);
  assert.equal(g.total, 2);
  const chips = rateChips(r.assumptions, { stock_allowance: 1.2 });
  assert.deepEqual(chips.bound, ["Labor rate $52/h", "Margin 30%"]);
  assert.deepEqual(chips.still, ["Region, labor ×1.00"]);
  assert.equal(assumptionValue("daily_machine_hours", 8, "hr/day"), "8 h/day");
  assert.equal(assumptionValue("complexity", 0, "very_complex"), "Very complex");
});

test("compare tables: change across quantity, one column per rate set", () => {
  const r = report();
  const t = compareByQty(r);
  assert.equal(t.qa, 1);
  assert.equal(t.qb, 100);
  assert.equal(t.rows[0].process, "binder_jetting");
  assert.equal(changeText(t.rows[0].change).text, "−98%");
  assert.equal(changeText(null).text, "—");
  const rates = compareByRates([{ id: "base", report: r }, { id: "shop", report: null }], 10);
  assert.equal(rates[0].cells.length, 2);
  assert.equal(rates[0].cells[1].unit, null);
});

test("history rows and the copied summary use the engine's own numbers", () => {
  const rows = historyRows([
    { id: "a", filename: "x", file_type: "iges", label: null, make_now_process: "wire_edm", crossover_qty: null, quantities: [1, 10, 10000], created_at: "2026-10-18T05:00:22Z", is_public: false, share_url: null, approval_status: "unreviewed" },
    { id: "b", filename: "x", file_type: "iges", label: null, make_now_process: null, crossover_qty: 4018, quantities: [10, 100], created_at: "2026-10-18T05:00:22Z", is_public: true, share_url: "/s/cost/q", approval_status: "approved" },
  ], "a");
  assert.equal(rows[0].title, "Make now: Wire EDM");
  assert.equal(rows[0].sub, "1 to 10,000 · no tooling crossover · this decision");
  assert.equal(rows[1].title, "No make-now pick");
  assert.equal(rows[1].sub, "10 and 100 · tooling pays off near 4,018");
  assert.equal(rows[1].tag, "Approved");
  assert.equal(rows[1].share, "Shared");
  const s = decisionSummary(report(), validation(), 10).split("\n");
  assert.equal(s[0], "ScaleCAD — bored-block-mm.iges");
  assert.equal(s[1], "Make by metal binder jetting / SS316L at quantity 10");
  assert.equal(s[2], "  qty 1: wire EDM — $110.00/unit, 7.7-14.3 days");
  assert.ok(s.includes("The lowest-cost no-tooling route varies by quantity. No tooling crossover is identified."));
  assert.equal(s[s.length - 1], "DFM · Metal binder jetting: issues to check");
  assert.match(decisionSummary(report(), null, 40), /Approximate at this quantity/);
});

test("small words", () => {
  assert.equal(qtyListText([5000, 50]), "50 and 5,000");
  assert.equal(qtyListText([1, 10, 10000]), "1 to 10,000");
  assert.equal(qtyListText([10]), "10");
  assert.equal(shortSource("Shop accounting export 2026-Q2 (loaded rates + negotiated resin lots)"), "Shop accounting export 2026-Q2");
  assert.equal(environmentLabel({ medium: "sour gas (H2S)", sour_service: true }), "Sour gas");
  assert.equal(environmentLabel({ corrosive: true }), "Corrosive service");
  assert.equal(environmentLabel(null), null);
  assert.equal(scenarioLabel(null, {}), "Engine");
  assert.equal(scenarioLabel("Midwest Precision CNC", { labor_rate: 40 }), "Midwest Precision CNC · labor_rate 40");
});

test("a tiny cycle time reads in seconds or minutes, never 0 h", () => {
  assert.equal(driverValue({ value: 0.00001, unit: "hr" }), "0.036 s");
  assert.equal(driverValue({ value: 0.004, unit: "hr" }), "14 s");
  assert.equal(driverValue({ value: 0.009, unit: "hr" }), "32 s");
  assert.equal(driverValue({ value: 0.0095, unit: "hr" }), "34 s");
  assert.equal(driverValue({ value: 1.25, unit: "hr" }), "1.25 h");
});

test("the Summary's 3D uses the part's kept preview, like the part page, and asks for the file only without one", () => {
  const base = { hasFile: false, part: "abc", kept: true as boolean | null | undefined, hasKeptMesh: true, keptError: null as string | null, filename: "bracket.step" };
  assert.deepEqual(threeSource(base), { kind: "kept" }, "kept with the part: no file needed");
  assert.deepEqual(threeSource({ ...base, hasFile: true }), { kind: "file" });
  assert.deepEqual(threeSource({ ...base, kept: undefined, hasKeptMesh: false }), { kind: "loading" });
  assert.deepEqual(threeSource({ ...base, kept: false, hasKeptMesh: false }), {
    kind: "needs-file",
    text: "bracket.step isn’t in this browser, and its file wasn’t kept with the part. Choose it again to turn the part and see findings on it.",
  });
  assert.deepEqual(threeSource({ ...base, hasKeptMesh: false, keptError: "The 3D view of the kept file couldn't reach the server." }), {
    kind: "kept-error",
    text: "The 3D view of the kept file couldn't reach the server.",
  });
  assert.equal(threeSource({ ...base, kept: null, hasKeptMesh: false, filename: null }).kind, "needs-file");
  assert.deepEqual(threeSource({ ...base, hasKeptMesh: false, keptError: "Service unavailable" }), { kind: "kept-error", text: "Service unavailable." }, "a sentence either way");
  assert.deepEqual(threeSource({ ...base, kept: false, hasKeptMesh: true }), { kind: "kept" }, "this browser's own copy counts too");
});

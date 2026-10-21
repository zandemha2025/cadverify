import test from "node:test";
import assert from "node:assert/strict";
import {
  buildMethods,
  chartModel,
  cheapestAt,
  costLines,
  decideOptions,
  fixesOf,
  groundedCount,
  groupUnpriced,
  interpolate,
  issueKind,
  machineViews,
  makeRows,
  methodWhy,
  otherQtyNote,
  progressSteps,
  routeAsk,
  biggestTypicalNote,
} from "./model.ts";

type AnyObj = Record<string, unknown>;

function est(process: string, material: string, quantity: number, unit: number, extra: AnyObj = {}) {
  return {
    process,
    material,
    quantity,
    unit_cost_usd: unit,
    fixed_cost_usd: 0,
    variable_cost_usd: unit,
    est_error_band_pct: 50,
    confidence: { low_usd: unit * 0.5, high_usd: unit * 1.5, point_usd: unit, level: 0.8, method: "assumption-band", validated: false, n_samples: 0, half_width_pct: 50, basis: "", label: "" },
    dfm_ready: true,
    dfm_verdict: "issues",
    dfm_score: 0.9,
    dfm_blockers: [],
    line_items: {},
    drivers: [
      { name: "labor_cost", value: unit * 0.55, unit: "$", provenance: "DEFAULT", source: "post-process 0.5 hr × $35/hr", error_band_pct: 20 },
      { name: "machine_cost", value: unit * 0.3, unit: "$", provenance: "USER", source: "0.02 hr × $85/hr", error_band_pct: 50 },
      { name: "material_cost", value: unit * 0.15, unit: "$", provenance: "MEASURED", source: "billet 3 cm³", error_band_pct: 5 },
      { name: "cycle_time", value: 0.02, unit: "hr", provenance: "DEFAULT", source: "rough + finish", error_band_pct: 50 },
    ],
    lead_time: { low_days: 5, high_days: 9, mid_days: 7, components: {}, capacity: {} },
    ...extra,
  };
}

function issue(code: string, severity: string, message: string, extra: AnyObj = {}) {
  return { code, severity, message, fix_suggestion: null, ...extra };
}

function fixture() {
  const validation = {
    filename: "block.iges",
    file_type: "iges",
    overall_verdict: "issues",
    best_process: "dlp",
    analysis_time_ms: 10100,
    geometry: { vertices: 10, faces: 100, volume_mm3: 2720, surface_area_mm2: 1432, bounding_box_mm: [20, 15, 10], is_watertight: true, is_manifold: true, center_of_mass: [0, 0, 0], units: "mm" },
    segments: [],
    universal_issues: [],
    process_scores: [
      { process: "dlp", score: 1.0, verdict: "issues", recommended_material: "Standard Resin", recommended_machine: null, estimated_cost_factor: null, issues: [issue("THIN_WALL", "warning", "Thin walls", { affected_faces_sample: [1, 2, 3], region_center: [1, 2, 3] })] },
      { process: "mjf", score: 0.9, verdict: "issues", recommended_material: "PP", recommended_machine: null, estimated_cost_factor: null, issues: [] },
      { process: "cnc_3axis", score: 0.8, verdict: "issues", recommended_material: "Delrin", recommended_machine: null, estimated_cost_factor: null, issues: [issue("SETUP_ACCESS_UNVERIFIED", "warning", "Tool reach not confirmed", { affected_faces_sample: [9] })] },
      { process: "cnc_turning", score: 0, verdict: "fail", recommended_material: null, recommended_machine: null, estimated_cost_factor: null, issues: [issue("NOT_ROTATIONALLY_SYMMETRIC", "error", "Not a turned part")] },
      { process: "injection_molding", score: 0, verdict: "fail", recommended_material: "PP", recommended_machine: null, estimated_cost_factor: null, issues: [issue("INSUFFICIENT_DRAFT", "error", "No draft on the walls", { affected_faces_sample: [4, 5] })] },
      { process: "dmls", score: 0.8, verdict: "issues", recommended_material: null, recommended_machine: null, estimated_cost_factor: null, issues: [] },
      { process: "slm", score: 0.9, verdict: "issues", recommended_material: null, recommended_machine: null, estimated_cost_factor: null, issues: [] },
    ],
    priority_fixes: [
      { code: "NOT_ROTATIONALLY_SYMMETRIC", severity: "error", message: "Not round", process: "cnc_turning", fix: "Use milling.\n\nAlternative: mill-turn.", measured_value: null, required_value: null },
      { code: "THIN_WALL", severity: "warning", message: "Thin", process: "", fix: null, measured_value: null, required_value: null },
    ],
  };
  const cost = {
    filename: "block.iges",
    status: "OK",
    reason: null,
    geometry: { volume_cm3: 2.72, surface_area_cm2: 14.32, bbox_mm: [20, 15, 10], watertight: true, face_count: 100 },
    material_class: "polymer",
    quantities: [1, 10, 100],
    estimates: [
      est("dlp", "Standard Resin", 1, 40), est("dlp", "Standard Resin", 10, 7.32), est("dlp", "Standard Resin", 100, 6.37),
      est("mjf", "PP", 1, 75), est("mjf", "PP", 10, 7.5), est("mjf", "PP", 100, 3.83),
      est("cnc_3axis", "Delrin", 1, 134.22), est("cnc_3axis", "Delrin", 10, 31.84), est("cnc_3axis", "Delrin", 100, 21.61),
      est("injection_molding", "PP", 1, 6002), est("injection_molding", "PP", 10, 602), est("injection_molding", "PP", 100, 2.5, { dfm_ready: false, dfm_verdict: "fail" }),
    ],
    engine_feasibility: [],
    notes: [],
    assumptions: [],
    routing: { archetype: "prismatic_block", recommended_process: "mjf", eval_family: "", material_hint: "", confidence: 0.4, reasoning: "A compact block.", alternatives: [], drivers: {} },
    decision: { make_now_process: "dlp", make_now_material: "Standard Resin", tooling_process: "injection_molding", tooling_dfm_ready: false, crossover_qty: 40, recommendation: {}, if_redesigned: {}, note: "" },
    verification: {
      verdict: "makeable_in_house",
      best_machine: "HP Jet Fusion 5200",
      inventory_declared: true,
      per_route: {
        mjf: { verdict: "makeable_in_house", machines_evaluated: 1, best_machine: "HP Jet Fusion 5200", failures: [] },
        cnc_turning: { verdict: "not_makeable", machines_evaluated: 1, best_machine: null, failures: [{ gate: "dfm", axis: "shape", need: null, have: null, human: "Part lacks rotational geometry; required for cnc_turning." }] },
      },
    },
    saved: { id: "01M56P47FRJC6CWQK304FKK5PG", url: "/x" },
  };
  const machines = [
    { id: "m1", name: "HP Jet Fusion 5200", process: "mjf", count: 1, max_workpiece_kg: 30, hourly_rate_usd: 45, capital_frac: null, capabilities: { x: 380, y: 284, z: 380 }, materials: ["polymer"], material_thickness_map: null, notes: null, provenance: "user", created_at: null, updated_at: null },
    { id: "m2", name: "Haas VF-2", process: "cnc_3axis", count: 1, max_workpiece_kg: 200, hourly_rate_usd: 85, capital_frac: null, capabilities: { x: 762, y: 406, z: 508 }, materials: ["stainless", "aluminum", "steel"], material_thickness_map: null, notes: null, provenance: "user", created_at: null, updated_at: null },
    { id: "m3", name: "Haas ST-20", process: "cnc_turning", count: 1, max_workpiece_kg: 200, hourly_rate_usd: 80, capital_frac: null, capabilities: { x: 254, y: 254, z: 533 }, materials: ["polymer"], material_thickness_map: null, notes: null, provenance: "user", created_at: null, updated_at: null },
  ];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return { validation: validation as any, cost: cost as any, machines: machines as any };
}

test("issue codes map to the board's four highlight kinds", () => {
  assert.equal(issueKind("THIN_WALL"), "thin");
  assert.equal(issueKind("THIN_WALL_MOLDING"), "thin");
  assert.equal(issueKind("OVERHANG"), "support");
  assert.equal(issueKind("CUPPING_RISK"), "support");
  assert.equal(issueKind("SETUP_ACCESS_UNVERIFIED"), "reach");
  assert.equal(issueKind("INSUFFICIENT_DRAFT"), "draft");
  assert.equal(issueKind("UNDERCUT_MOLDING"), "draft");
  assert.equal(issueKind("CONDUCTIVITY_REQUIRED"), null);
});

test("methods carry the engine's verdicts, reasons and prices", () => {
  const f = fixture();
  const methods = buildMethods(f);
  const by = new Map(methods.map((m) => [m.code, m]));
  assert.equal(by.get("dlp")!.verdict, "ok");
  assert.equal(by.get("dlp")!.geometryPick, true);
  assert.equal(by.get("dlp")!.finding!.kind, "thin");
  assert.deepEqual(by.get("dlp")!.finding!.faces, [1, 2, 3]);
  assert.equal(by.get("cnc_3axis")!.verdict, "warn", "an unverified setup reads Check first");
  assert.equal(by.get("cnc_turning")!.verdict, "bad");
  assert.equal(by.get("cnc_turning")!.blockedReason, "Part lacks rotational geometry; required for cnc_turning.", "the DFM gate's own human text wins");
  assert.equal(by.get("injection_molding")!.blockedReason, "No draft on the walls");
  assert.equal(by.get("mjf")!.inHouse, "HP Jet Fusion 5200");
  assert.equal(by.get("mjf")!.routePick, true);
  assert.equal(cheapestAt(methods, 10)!.code, "dlp");
  assert.equal(cheapestAt(methods, 100)!.code, "mjf", "a DFM-blocked route never wins cheapest");
});

test("unpriced metal-only methods collapse into one row; rows rank cheapest first per family", () => {
  const f = fixture();
  const grouped = groupUnpriced(buildMethods(f));
  const metal = grouped.find((m) => m.code === "group:metalprint")!;
  assert.equal(metal.name, "Metal printing, 2 ways");
  assert.deepEqual(metal.scoreRange, [0.8, 0.9]);
  assert.equal(methodWhy(metal, "polymer"), "Priced once you choose a metal.");
  const rows = makeRows(grouped, 10);
  assert.equal(rows[0].kind, "group");
  assert.equal(rows[0].right, "each at 10");
  const print = rows.slice(1, rows.findIndex((r, i) => i > 0 && r.kind === "group")).map((r) => r.method!.code);
  assert.deepEqual(print, ["dlp", "mjf", "group:metalprint"]);
});

test("cost lines come from the dollar drivers, largest first, with provenance", () => {
  const f = fixture();
  const e = f.cost.estimates[4];
  const lines = costLines(e);
  assert.deepEqual(lines.map((l) => l.name), ["Labor", "Machine", "Material"]);
  assert.deepEqual(lines.map((l) => l.src.label), ["Typical", "Yours", "Your file"]);
  assert.deepEqual(groundedCount(e), { grounded: 2, total: 4 });
  const note = biggestTypicalNote(e, "in-house")!;
  assert.match(note.title, /^Labor is half of the in-house cost/);
});

test("other quantities interpolate between computed points and say so", () => {
  const f = fixture();
  const methods = buildMethods(f);
  const dlp = methods.find((m) => m.code === "dlp")!;
  assert.equal(interpolate(dlp, [1, 10, 100], 10), 7.32);
  const mid = interpolate(dlp, [1, 10, 100], 31.62)!;
  assert.ok(mid < 7.32 && mid > 6.37);
  const note = otherQtyNote(methods, [1, 10, 100], "50");
  assert.equal(note.on, true);
  assert.match(note.text, /between 10 and 100\. Decide at a computed quantity\./);
  assert.equal(otherQtyNote(methods, [1, 10, 100], "10").on, false);
  assert.match(otherQtyNote(methods, [1, 10, 100], "").text, /Computed at 1, 10 and 100\./);
});

test("the chart places quantities on a log axis and snaps drags to computed points", () => {
  const f = fixture();
  const methods = buildMethods(f);
  const c = chartModel(methods, [1, 10, 100], 10, "dlp", 40);
  assert.equal(c.x(1), 90);
  assert.equal(c.x(100), 690);
  assert.equal(Math.round(c.x(10)), 390);
  assert.ok(c.crossoverX! > c.x(10) && c.crossoverX! < c.x(100));
  assert.equal(c.qFromX(400), 10);
  const sel = c.lines.find((l) => l.code === "dlp")!;
  assert.equal(sel.stroke, "#141414");
  assert.equal(c.lines.find((l) => l.code === "injection_molding")!.dash, "5 5");
  assert.equal(c.lines.find((l) => l.code === "mjf")!.stroke, "#5B3FC4");
});

test("machines say whether they can make it, and why not", () => {
  const f = fixture();
  const methods = buildMethods(f);
  const views = machineViews(f.machines, methods, f.cost, 10, [20, 15, 10]);
  const [hp, vf2, st20] = views;
  assert.equal(hp.verdict, "Can make");
  assert.equal(hp.cost, 7.5);
  assert.match(hp.checks, /Size ✓ · weight ✓ · material ✓/);
  assert.equal(vf2.verdict, "Not set up");
  assert.equal(vf2.why, "Declared for stainless, aluminum and steel, not plastic.");
  assert.equal(st20.verdict, "Can't");
  assert.equal(st20.why, "Part lacks rotational geometry; required for cnc_turning.");
});

test("decide offers the real routes and binds each to an exact estimate", () => {
  const f = fixture();
  const methods = buildMethods(f);
  const opts = decideOptions(methods, f.cost, 10, 3);
  const inhouse = opts.find((o) => o.kind === "inhouse")!;
  assert.equal(inhouse.off, false);
  assert.deepEqual(inhouse.route, { process: "mjf", material: "PP", quantity: 10 });
  const outside = opts.filter((o) => o.kind === "outside");
  assert.deepEqual(outside.map((o) => o.route!.process), ["dlp", "cnc_3axis"], "in-house route is not repeated as outside");
  const redesign = opts.find((o) => o.kind === "redesign")!;
  assert.equal(redesign.route!.process, "injection_molding");
  const none = decideOptions(methods.map((m) => ({ ...m, inHouse: null })), f.cost, 10, 0);
  assert.equal(none[0].off, true);
  assert.equal(none[0].sub, "No machines declared yet");
});

test("progress reports each stage from real responses, and stops at an open shell", () => {
  const f = fixture();
  const base = { fileName: "block.iges", sample: false, validation: null, cost: null, costError: null, geometryInvalid: null, done: false };
  const running = progressSteps(base);
  assert.deepEqual(running.map((s) => s.state), ["done", "now", "wait", "wait", "wait"]);
  const done = progressSteps({ ...base, validation: f.validation, cost: f.cost, done: true });
  assert.deepEqual(done.map((s) => s.state), ["done", "done", "done", "done", "done"]);
  assert.equal(done[1].d, "20 × 15 × 10 mm · 2.72 cm³ · watertight");
  assert.equal(done[2].d, "Solid block → MJF · confidence 0.40");
  assert.equal(done[3].d, "HP Jet Fusion 5200 clears every check");
  assert.equal(done[4].d, "Record 01M56P47");
  const open = { ...f.validation, geometry: { ...f.validation.geometry, is_watertight: false } };
  const stopped = progressSteps({ ...base, validation: open, geometryInvalid: "not watertight" });
  assert.deepEqual(stopped.map((s) => s.state), ["done", "bad", "skip", "skip", "skip"]);
  const sample = progressSteps({ ...base, fileName: "sample-routing-bracket.stl", sample: true });
  assert.equal(sample.length, 3);
  assert.equal(sample[0].d, "Reading the shape now…");
});

test("fixes keep the engine's order and severity", () => {
  const fixes = fixesOf(fixture().validation);
  assert.deepEqual(fixes.map((x) => [x.where, x.fix, x.sev]), [["Turning", "Use milling.", "Blocks"], ["Every process", "Thin", "Check"]]);
});

test("typed asks route to answers this part can give, or a refusal", () => {
  const methods = buildMethods(fixture());
  assert.deepEqual(routeAsk("lathe?", methods), { kind: "method", code: "cnc_turning" });
  assert.deepEqual(routeAsk("lead time?", methods), { kind: "lead" });
  assert.deepEqual(routeAsk("cost drivers", methods), { kind: "drivers" });
  assert.deepEqual(routeAsk("cheapest at 1,000", methods), { kind: "routes", qty: 1000 });
  assert.deepEqual(routeAsk("why this verdict", methods), { kind: "why" });
  assert.deepEqual(routeAsk("supplier pricing pressure", methods), { kind: "refuse" });
});

test("a whole-file error (an open shell) stops every method, even one whose own score passed", () => {
  const validation = {
    filename: "open.iges",
    file_type: "iges",
    overall_verdict: "fail",
    best_process: "dlp",
    analysis_time_ms: 1,
    geometry: { vertices: 3, faces: 1, volume_mm3: 0, surface_area_mm2: 1, bounding_box_mm: [20, 15, 10], is_watertight: false, is_manifold: false, center_of_mass: [0, 0, 0], units: "mm" },
    segments: [],
    universal_issues: [issue("NON_WATERTIGHT", "error", "Mesh is not watertight — has 945 boundary edges. All manufacturing processes require a closed solid.")],
    process_scores: [
      { process: "dlp", verdict: "issues", score: 1, issues: [], recommended_material: null, recommended_machine: null, estimated_cost_factor: 1 },
      { process: "fdm", verdict: "pass", score: 1, issues: [], recommended_material: null, recommended_machine: null, estimated_cost_factor: 1 },
    ],
    priority_fixes: [],
  };
  const ms = buildMethods({ validation: validation as never, cost: null, machines: [] });
  assert.deepEqual(ms.map((m) => m.verdict), ["bad", "bad"]);
  assert.match(ms[0].blockedReason!, /boundary edges/);
});

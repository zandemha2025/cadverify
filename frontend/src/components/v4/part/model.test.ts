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
  issueKind,
  machineViews,
  makeRows,
  methodWhy,
  modelPrice,
  otherQtyNote,
  withQuantity,
  materialText,
  METHODS,
  progressSteps,
  routeAsk,
  biggestTypicalNote,
  ratesNote,
  verdictAnswer,
} from "./model.ts";
import type { Method } from "./model.ts";
import type { CostEstimate } from "@/lib/api";

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

test("a process the engine won't price for this part is ruled out in its words, not Can make (buyer-02)", () => {
  const f = fixture();
  const why = "Wire-arc printing (WAAM) is for large near-net metal parts: … under 100 mm on the longest side (this part: 20 mm).";
  f.validation.process_scores.push({ process: "waam", score: 1, verdict: "pass", recommended_material: null, recommended_machine: null, estimated_cost_factor: null, issues: [] });
  f.cost.engine_feasibility = [{ process: "waam", verdict: "pass", score: 1, costed: false, blockers: [], cost_exclusion_reason: why }];
  const waam = buildMethods(f).find((m) => m.code === "waam")!;
  assert.equal(waam.verdict, "out");
  assert.equal(methodWhy(waam, "aluminum"), why);
  assert.equal(cheapestAt([waam], 10), null);
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

test("other quantities: no straight line between priced points; no model, no number (ce-06)", () => {
  const f = fixture();
  const methods = buildMethods(f);
  // This record was priced before the model was kept: no quick number at all.
  const note = otherQtyNote(methods, [1, 10, 100], "50");
  assert.equal(note.on, true);
  assert.equal(note.value, null);
  assert.match(note.text, /^Not priced at 50 yet/);
  assert.doesNotMatch(note.text, /≈|between/);
  assert.equal(otherQtyNote(methods, [1, 10, 100], "10").on, false);
  assert.match(otherQtyNote(methods, [1, 10, 100], "").text, /Computed at 1, 10 and 100\./);
});

test("other quantities: the model's own price, with the words that add up to it (ce-06)", () => {
  // The cost engineer's pocket block, steel, 3-axis at v0 rates, priced at 1 and 100.
  const qty_model = {
    v: 1, once_usd: 113.75, per_part_usd: 1.306914, machine_usd: 15.693375, learning_usd: 18.55,
    learning: { rate: 0.9, first_lot: 100, floor: 0.25 }, per_plate: [], order_min_usd: 90, specs: [],
  };
  const est = (q: number, unit: number) => ({ process: "cnc_3axis", material: "Mild Steel", quantity: q, unit_cost_usd: unit, qty_model }) as unknown as CostEstimate;
  const m = { code: "cnc_3axis", name: "3-axis milling", verdict: "ok", excludedReason: null, prices: new Map([[1, est(1, 149.3)], [100, est(100, 36.69)]]) } as unknown as Method;
  assert.equal(modelPrice(m, [1, 100], 25)!.value.toFixed(2), "40.10");
  // Beyond the last priced quantity it is still the model, not the 100-off price held flat.
  assert.equal(modelPrice(m, [1, 100], 10000)!.value.toFixed(2), "27.84");
  const note = otherQtyNote([m], [1, 100], "25");
  assert.equal(note.value!.toFixed(2), "40.10");
  // $113.75 ÷ 25 = $4.55, + $35.55 = $40.10
  assert.equal(note.text, "$40.10 each by 3-axis milling at 25, from the model's own lines: $113.75 once for the order ÷ 25 + $35.55 a part.");
});

test("a typed quantity is priced by the model: it joins the quantities the engine computes (de-18)", () => {
  // The engine prices six quantities at most: the one closest to a neighbour gives way.
  assert.deepEqual(withQuantity([1, 100, 1000, 2000, 5000, 10000], 10), [1, 10, 100, 1000, 5000, 10000]);
  assert.deepEqual(withQuantity([1, 100, 1000], 10), [1, 10, 100, 1000]);
  assert.deepEqual(withQuantity([1, 10, 100], 10), [1, 10, 100]);
  // The first, the last and the asked quantity always stay.
  assert.deepEqual(withQuantity([1, 2, 5, 10, 20, 50], 100000), [1, 2, 5, 20, 50, 100000]);
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
  assert.equal(vf2.why, "Declared for stainless, aluminum and steel, not Delrin.");
  assert.equal(st20.verdict, "Can't");
  assert.equal(st20.why, "Part lacks rotational geometry; required for cnc_turning.");
});

test("a printer declared for the route's own material can make it (feedback 15)", () => {
  const f = fixture();
  // An unedited catalog X1C declares filament names, not the class "polymer".
  const x1c = { ...f.machines[0], id: "m9", name: "Bambu Lab X1C", process: "fdm", materials: ["PLA", "PETG", "ABS", "Nylon (PA6)", "TPU 95A"] };
  const cost = { ...f.cost, estimates: [...f.cost.estimates, est("fdm", "PLA", 10, 15.66)], verification: { ...f.cost.verification, per_route: { ...f.cost.verification.per_route, fdm: { verdict: "makeable_in_house", machines_evaluated: 1, best_machine: "Bambu Lab X1C", failures: [] } } } };
  const methods = buildMethods({ ...f, cost, machines: [x1c] as never });
  const [v] = machineViews([x1c] as never, methods, cost, 10, [20, 15, 10]);
  assert.equal(v.verdict, "Can make");
  assert.equal(v.cost, 15.66);
  assert.match(v.checks, /material ✓/);
  // Declared for other filaments only, and no engine fit: not set up, naming the route's material.
  const petg = { ...x1c, materials: ["PETG"] };
  const bare = { ...cost, verification: { ...cost.verification, per_route: {} } };
  const [w] = machineViews([petg] as never, buildMethods({ ...f, cost: bare, machines: [petg] as never }), bare, 10, [20, 15, 10]);
  assert.equal(w.verdict, "Not set up");
  assert.equal(w.why, "Declared for PETG, not PLA.");
});

test("a machine that fits but needs something never declared reads can't confirm (audit W1/M2)", () => {
  const f = fixture();
  const eos = { ...f.machines[0], id: "m7", name: "EOS M 400-4", process: "mjf" };
  const cost = { ...f.cost, verification: { ...f.cost.verification, verdict: "unknown", per_route: { mjf: { verdict: "unknown", machines_evaluated: 1, best_machine: "EOS M 400-4", failures: [{ gate: "secondary_op", axis: "stress_relief", need: "stress_relief", have: null, human: "needs stress relief afterwards; not declared whether you do it in-house" }] } } } };
  const [v] = machineViews([eos] as never, buildMethods({ ...f, cost, machines: [eos] as never }), cost, 10, [20, 15, 10]);
  assert.equal(v.verdict, "Can't confirm");
  assert.equal(v.tone, "warn");
  assert.equal(v.why, "Not declared on Your shop: stress relief. Declare what you do in-house, send out or hold to confirm.");
  // A part spec's op and certification read the same way, in words.
  const cost2 = { ...cost, verification: { ...cost.verification, per_route: { mjf: { ...cost.verification.per_route.mjf, failures: [
    { gate: "secondary_op", axis: "anodize_ii", need: "anodize_ii", have: null, human: "needs Type II anodizing; not declared" },
    { gate: "certification", axis: "as9100", need: "AS9100", have: null, human: "needs AS9100; not declared" },
  ] } } } };
  const [v2] = machineViews([eos] as never, buildMethods({ ...f, cost: cost2, machines: [eos] as never }), cost2, 10, [20, 15, 10]);
  assert.equal(v2.why, "Not declared on Your shop: Type II anodizing and AS9100. Declare what you do in-house, send out or hold to confirm.");
});

test("a metal printer that fits says it assumes the shop's own stress relief (round 7)", () => {
  const f = fixture();
  const eos = { ...f.machines[0], id: "m7", name: "EOS M 400-4", process: "mjf", materials: ["PP"] };
  const fit = { verdict: "makeable_with_secondary_op", machines_evaluated: 1, best_machine: "EOS M 400-4", failures: [], secondary_ops: ["stress_relief"], assumed_in_house: ["stress_relief"] };
  const cost = { ...f.cost, verification: { ...f.cost.verification, verdict: "makeable_with_secondary_op", per_route: { mjf: fit } } };
  const [v] = machineViews([eos] as never, buildMethods({ ...f, cost, machines: [eos] as never }), cost, 10, [20, 15, 10]);
  assert.equal(v.verdict, "Can make");
  assert.equal(v.tone, "ok");
  assert.match(v.why, / Assumes your shop does its own stress relief; change this in Your shop\.$/);
  assert.doesNotMatch(v.why, /Needs stress relief afterwards/);
  // Declared in-house: a step it needs, not an assumption.
  const done = { ...cost, verification: { ...cost.verification, per_route: { mjf: { ...fit, assumed_in_house: undefined } } } };
  const [w] = machineViews([eos] as never, buildMethods({ ...f, cost: done, machines: [eos] as never }), done, 10, [20, 15, 10]);
  assert.match(w.why, / Needs stress relief afterwards\.$/);
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

test("setup reads once per plate when printing, shared over the order on a machine (de-19)", () => {
  const plate = { name: "setup_cost", value: 0.05, unit: "$", provenance: "DEFAULT", source: "setup 0.25hr × $35/hr per plate × 100/40 parts a plate = 2.5 plates (at least one) ÷ 100", error_band_pct: 20 };
  const order = { ...plate, source: "setup 0.75hr × $35/hr once for the order ÷ 1000" };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const lines = (d: any, q: number) => costLines({ drivers: [d], quantity: q, unit_cost_usd: 1 } as any).map((l) => l.name);
  assert.deepEqual(lines(plate, 100), ["Setup, one per plate"]);
  assert.deepEqual(lines(order, 1000), ["Setup, shared over 1,000"]);
});

test("one material story per page: a process that can't run the page's class says so (de-06, np-17)", () => {
  const info = (code: string) => METHODS[code];
  // Priced in plastic: the grade; never the first alloy on the process's list.
  assert.equal(materialText("cnc_3axis", info("cnc_3axis"), "Delrin (POM)", "polymer", true), "Delrin (POM)");
  assert.equal(materialText("wire_edm", info("wire_edm"), null, "polymer", true), "can’t run plastic");
  assert.equal(materialText("investment_casting", info("investment_casting"), null, "polymer", true), "can’t run plastic");
  assert.equal(materialText("sheet_metal", info("sheet_metal"), "5052 Aluminum (Sheet)", "polymer", true), "5052 Aluminum (Sheet), can’t run plastic");
  // Turning isn't priced (the part isn't round): no grade named, the row's verdict says why.
  assert.equal(materialText("cnc_turning", info("cnc_turning"), null, "polymer", true), null);
  assert.equal(materialText("injection_molding", info("injection_molding"), null, "aluminum", true), "can’t run aluminum");
  // Not priced yet: nothing named.
  assert.equal(materialText("forging", info("forging"), null, null, false), null);
});

test("a grouped row speaks for every member: casting and forging split by verdict (de-10)", () => {
  const f = fixture();
  const methods = buildMethods(f);
  const like = (code: string, verdict: "ok" | "bad", score: number) => ({ ...methods[0], code, name: METHODS[code].name, short: METHODS[code].short, prices: new Map(), verdict, score, scoreRange: [score, score] as [number, number], members: [code] });
  const rows = groupUnpriced([like("die_casting", "ok", 0.8), like("sand_casting", "bad", 0), like("forging", "bad", 0)]);
  const die = rows.find((m) => m.code === "die_casting")!;
  assert.equal(die.verdict, "ok");
  const blocked = rows.find((m) => m.code === "group:cast")!;
  assert.equal(blocked.verdict, "bad");
  assert.deepEqual(blocked.members, ["sand_casting", "forging"]);
  assert.equal(blocked.name, "Casting and forging, 2 ways");
});

test("an order minimum and finish machining are named lines (de-20)", () => {
  const floor = { name: "min_charge_floor", value: 120, unit: "$", provenance: "DEFAULT", source: "order minimum $300 ÷ 1 = $300.00 a part (applied)", error_band_pct: null };
  const mill = { name: "finish_machining", value: 40, unit: "$", provenance: "DEFAULT", source: "finish machining on a 3-axis mill", error_band_pct: 50 };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const names = (q: number) => costLines({ drivers: [floor, mill], quantity: q, unit_cost_usd: 300 } as any).map((l) => l.name).sort();
  assert.deepEqual(names(1), ["Finish machining", "Order minimum, on one part"]);
  assert.deepEqual(names(10), ["Finish machining", "Order minimum, shared over 10"]);
});

test("ce-16 / me-05: the labor line at the org's published $58/h reads \"Your rates v1\" and drops \"Add your labor rate\"", () => {
  // Pocket block at 100 off, rates v1: labor 0.5 h x $58 = $29.00 of $49.63
  const e = {
    quantity: 100,
    unit_cost_usd: 49.63,
    drivers: [
      { name: "labor_cost", value: 29, unit: "$", provenance: "SHOP", source: "post-process 0.5 hr x $58/hr; $58/h labor rate from your rates v1", error_band_pct: 20, rate_card: 1 },
      { name: "machine_cost", value: 15.6934, unit: "$", provenance: "DEFAULT", source: "0.209245 h x $75/hr", error_band_pct: 30 },
    ],
  } as unknown as CostEstimate;
  const [labor, machine] = costLines(e);
  assert.equal(labor.src.label, "Your rates v1");
  assert.equal(labor.src.kind, "yours");
  assert.match(labor.band, /rate from your rates v1/);
  assert.equal(machine.src.label, "Typical");
  assert.equal(groundedCount(e).grounded, 1);
  // the biggest line is hers now: no "it's a typical value ... Add your labor rate" note
  assert.equal(biggestTypicalNote(e, "process"), null);
});

test("a record priced at older rates says so near the price; current rates say nothing (ce-10)", () => {
  assert.equal(ratesNote({ rates: { priced: 0, current: 1, out_of_date: true, text: "Priced at rates v0; your rates are v1." } }), "Priced at rates v0; your rates are v1.");
  assert.equal(ratesNote({ rates: { priced: 0, current: 1, out_of_date: true, text: "" } }), "Priced at rates v0; your rates are v1.");
  assert.equal(ratesNote({ rates: { priced: 1, current: 1, out_of_date: false, text: "Priced at your rates v1." } }), null);
  assert.equal(ratesNote({ rates: null }), null);
  assert.equal(ratesNote(null), null);
});

test("Why this verdict? counts the problems the page lists, never 'no problems found' over them (R3 hand-off)", () => {
  const f = fixture();
  f.validation.overall_verdict = "pass";
  const methods = buildMethods(f);
  const a = verdictAnswer(methods, f.validation, f.cost, [{ severity: "error" }, { severity: "warning" }, { severity: "warning" }]);
  assert.match(a.text, /3 problems on this part, 1 stops a process\.$/);
  assert.doesNotMatch(a.text, /no problems found/);
  assert.match(verdictAnswer(methods, f.validation, f.cost, []).text, /No problems found on this part\.$/);
});

test("where the price comes from: the lines add up to it, with a Rounding line (ce-01)", () => {
  // Her pocket block, 3-axis at 100: 0.70 + 17.50 + 15.69 + 0.52 + 1.23 + 0.78 + 0.26 = 36.68 against $36.69.
  const d = (name: string, value: number, unit = "$") => ({ name, value, unit, provenance: "DEFAULT", source: `${name} formula`, error_band_pct: 40 });
  const e = {
    process: "cnc_3axis", material: "Mild Steel", quantity: 100, unit_cost_usd: 36.69,
    line_items: { nre: 0.7, labor: 17.5, machine: 15.6934, material: 0.5222, inspection: 1.225, consumables: 0.7847, amortized_fixed: 0.2625 },
    drivers: [d("material_cost", 0.5222), d("machine_cost", 15.6934), d("cycle_time", 0.2092, "hr"), d("labor_cost", 17.5),
      d("setup_cost", 0.2625), d("nre_cost", 0.7), d("inspection_cost", 1.225), d("consumables_cost", 0.7847)],
  } as unknown as CostEstimate;
  const lines = costLines(e);
  assert.deepEqual(lines.map((l) => [l.key, l.value]), [
    ["labor_cost", 17.5], ["machine_cost", 15.69], ["inspection_cost", 1.23], ["consumables_cost", 0.78],
    ["nre_cost", 0.7], ["material_cost", 0.52], ["setup_cost", 0.26], ["rounding", 0.01],
  ]);
  assert.equal(lines.reduce((s, l) => s + Math.round(l.value * 100), 0), 3669);
  assert.match(lines.at(-1)!.how, /unrounded they add to \$36\.6878, which is \$36\.69/);
  // A whole tool ("$/tool") is never a line; the tool's share a part is.
  const cast = {
    ...e, quantity: 100, unit_cost_usd: 78.23,
    line_items: { amortized_fixed: 0.35, material: 0.8557, machine: 3.5229, labor: 21.0, tooling: 52.5 },
    drivers: [d("setup_cost", 0.35), d("material_cost", 0.8557), d("machine_cost", 3.5229), d("labor_cost", 21), d("tooling_cost", 5250, "$/tool"), d("tooling_per_part", 52.5)],
  } as unknown as CostEstimate;
  const cl = costLines(cast);
  assert.deepEqual(cl.map((l) => l.name), ["Tooling, shared over 100", "Labor", "Machine", "Material", "Setup, shared over 100"]);
  assert.equal(cl.reduce((s, l) => s + l.value, 0).toFixed(2), "78.23");
});

import test from "node:test";
import assert from "node:assert/strict";
import {
  IDENTITY,
  candidateFacts,
  candidateFor,
  candidateName,
  compare,
  downTo,
  exact,
  fromParam,
  label,
  mul,
  orientationParam,
  priceBasis,
  PRICES_LINE,
  flagWords,
  fitWords,
  layerWords,
  rankedFor,
  recordOf,
  matOf,
  same,
  shadeFaces,
  shadeFor,
  turned,
  upWord,
  whyLine,
  type Candidate,
  type Options,
} from "./orient.ts";

type AnyObj = Record<string, unknown>;

test("quarter turns compose exactly and match the backend's names and keys", () => {
  // turns:x90 on the backend is rotation:1,0,0,0,0,-1,0,1,0, "File +Y up".
  const x90 = turned(IDENTITY, "x");
  assert.deepEqual(x90, [1, 0, 0, 0, 0, -1, 0, 1, 0]);
  assert.equal(orientationParam(x90), "rotation:1,0,0,0,0,-1,0,1,0");
  assert.equal(label(x90), "File +Y up");
  assert.equal(orientationParam(IDENTITY), null);
  assert.equal(label(IDENTITY), "As in the file");
  // Four quarter turns about any axis come back exactly; 24 distinct orientations in all.
  for (const axis of ["x", "y", "z"] as const) {
    let r = IDENTITY;
    for (let i = 0; i < 4; i++) r = turned(r, axis);
    assert.deepEqual(r, IDENTITY);
  }
  const seen = new Set<string>();
  const walk = (r: number[], depth: number) => {
    seen.add(orientationParam(r) ?? "id");
    if (depth === 0) return;
    for (const axis of ["x", "y", "z"] as const) walk(turned(r, axis), depth - 1);
  };
  walk(IDENTITY, 5);
  assert.equal(seen.size, 24);
  for (const key of seen) if (key !== "id") assert.ok(exact(fromParam(key)), key);
  assert.deepEqual(fromParam(orientationParam(x90)), x90);
  assert.deepEqual(mul(turned(IDENTITY, "x", -1), x90), IDENTITY);
});

test("laying a face down is the backend's rotation_down", () => {
  // The backend's matrices for each side (src/analysis/orientation.py rotation_down).
  const backend: [number[], number[]][] = [
    [[0, 0, -1], IDENTITY],
    [[0, 0, 1], [1, 0, 0, 0, -1, 0, 0, 0, -1]],
    [[-1, 0, 0], [0, 0, -1, 0, 1, 0, 1, 0, 0]],
    [[1, 0, 0], [0, 0, 1, 0, 1, 0, -1, 0, 0]],
    [[0, -1, 0], [1, 0, 0, 0, 0, -1, 0, 1, 0]],
    [[0, 1, 0], [1, 0, 0, 0, 0, 1, 0, -1, 0]],
  ];
  for (const [d, r] of backend) assert.deepEqual(downTo(d), r, JSON.stringify(d));
  const tilted = downTo([1, 1, -1])!;
  const expect = [0.788675, -0.211325, 0.57735, -0.211325, 0.788675, 0.57735, -0.57735, -0.57735, 0.57735];
  tilted.forEach((v, i) => assert.ok(Math.abs(v - expect[i]) < 1e-6));
  assert.ok(!exact(tilted));
  assert.match(label(tilted), /^Tilted: file direction \(-?0\.58, -?0\.58, 0\.58\) up$/);
  assert.equal(downTo([0, 0, 0]), null);
  assert.equal(upWord(downTo([0, -1, 0])), "+Y");
  assert.equal(upWord(null), "+Z");
});

/** A 1 mm cube on the plate (12 triangles), and one downward triangle hanging at z = 5. */
function scene(): Float32Array {
  const v = (x: number, y: number, z: number) => [x, y, z];
  const quads = [
    [v(0, 0, 0), v(0, 1, 0), v(1, 1, 0), v(1, 0, 0)], // bottom (-Z)
    [v(0, 0, 1), v(1, 0, 1), v(1, 1, 1), v(0, 1, 1)], // top (+Z)
    [v(0, 0, 0), v(1, 0, 0), v(1, 0, 1), v(0, 0, 1)], // -Y
    [v(0, 1, 0), v(0, 1, 1), v(1, 1, 1), v(1, 1, 0)], // +Y
    [v(0, 0, 0), v(0, 0, 1), v(0, 1, 1), v(0, 1, 0)], // -X
    [v(1, 0, 0), v(1, 1, 0), v(1, 1, 1), v(1, 0, 1)], // +X
  ];
  const tris: number[] = [];
  for (const [a, b, c, d] of quads) tris.push(...a, ...b, ...c, ...a, ...c, ...d);
  tris.push(0, 0, 5, 0, 1, 5, 1, 0, 5); // faces down, hanging above the plate
  return new Float32Array(tris);
}

test("the 3D shading uses the check's own overhang and draft rules", () => {
  const pos = scene();
  // As in the file: only the hanging triangle; the bottom rests on the plate.
  assert.deepEqual(shadeFaces(pos, IDENTITY, { kind: "overhang", deg: 45 }), [12]);
  // Upside down: the cube's top now faces down, above the hanging triangle (now lowest).
  assert.deepEqual(shadeFaces(pos, downTo([0, 0, 1])!, { kind: "overhang", deg: 45 }), [2, 3]);
  // Draft: the four side walls (eight triangles) are exactly vertical.
  assert.deepEqual(shadeFaces(pos, IDENTITY, { kind: "draft", deg: 1 }), [4, 5, 6, 7, 8, 9, 10, 11]);
  // Laid on its -Y side, the old top and bottom become walls without draft.
  assert.deepEqual(shadeFaces(pos, downTo([0, -1, 0])!, { kind: "draft", deg: 1 }).slice(0, 4), [0, 1, 2, 3]);
});

const rules = { fdm: { overhang_deg: 45 }, sla: { overhang_deg: 19 }, injection_molding: { draft_deg: 1 } };

function cand(id: string, up: number[], support: number, height: number, draft = 0, extra: AnyObj = {}): Candidate {
  return {
    id, basis: "side", rotation: [[1, 0, 0], [0, 1, 0], [0, 0, 1]], orientation: null, label: "", up_in_file: up, down_in_file: up.map((c) => -c),
    exact: true, height_mm: height, footprint_mm: [60, 40], on_plate_area_mm2: 100,
    support: { fdm: { faces: support ? 2 : 0, area_mm2: support }, sla: { faces: support ? 2 : 0, area_mm2: support } },
    draft: { injection_molding: { faces: draft ? 9 : 0, area_mm2: draft } }, downward_area_mm2: 0, downward_share_pct: 0, ...extra,
  } as Candidate;
}

const options: Options = {
  mesh_hash: "h", faces: 10, analysed_faces: 10, decimated: false, surface_area_mm2: 1000, rules,
  candidates: [cand("down-z", [0, 0, 1], 0, 45, 4788), cand("down+z", [0, 0, -1], 2160, 45, 4788), cand("down-y", [0, 1, 0], 0, 40, 8400)],
  best: { fdm: "down-y", injection_molding: "down-z" }, ranking: { printing: "", molding: "" }, limits: [],
};

test("ways to lay it down rank like the backend and read in plain words", () => {
  assert.deepEqual(rankedFor(options, "fdm").map((c) => c.id), ["down-y", "down-z", "down+z"]);
  assert.equal(rankedFor(options, "fdm")[0].id, options.best.fdm);
  assert.deepEqual(rankedFor(options, "injection_molding").map((c) => c.id), ["down-z", "down+z", "down-y"]);
  assert.deepEqual(rankedFor(options, "cnc_3axis").map((c) => c.id), ["down-z", "down+z", "down-y"]);
  assert.equal(candidateFor(options, turned(IDENTITY, "x"))?.id, "down-y");
  assert.equal(candidateFor(options, turned(turned(IDENTITY, "x"), "z"))?.id, "down-y"); // a spin keeps up
  assert.deepEqual(candidateFacts(options.candidates[1], "fdm", rules), { main: "Support on 2,160 mm²", sub: "45 mm tall · 60 × 40 mm on the plate" });
  // With the engine's layer, work-area and support-space figures (the L-bracket upside down).
  const upside = { ...options.candidates[1], layers: { fdm: 225 }, fits: { fdm: true }, flags: { fdm: ["OVERHANG"], sla: ["OVERHANG", "CUPPING_RISK"] }, support: { ...options.candidates[1].support, fdm: { faces: 28242, area_mm2: 2160, volume_cm3: 84.24 } } };
  const full = { ...options, layer_mm: { fdm: 0.2 }, work_areas_mm: { fdm: [300, 300, 350] } };
  assert.deepEqual(candidateFacts(upside, "fdm", rules, full), {
    main: "Support on 2,160 mm², about 84 cm³ under it (estimate)",
    sub: "45 mm tall · 225 layers at 0.2 mm · 60 × 40 mm on the plate · fits the 300 × 300 × 350 mm work area",
  });
  assert.equal(flagWords(upside, "sla"), "needs support, cupping risk in the resin tank");
  assert.equal(flagWords(upside, "cnc_3axis"), "");
  assert.equal(fitWords({ ...upside, fits: { fdm: false } }, "fdm", full), "doesn't fit the 300 × 300 × 350 mm work area standing this way");
  assert.equal(layerWords(upside, "sla", full), null);
  assert.match(PRICES_LINE, /don't yet include support material or print height/);
  assert.equal(candidateFacts(options.candidates[2], "fdm", rules).main, "No support needed");
  assert.equal(candidateFacts(options.candidates[0], "injection_molding", rules).main, "4,788 mm² of wall without 1° draft");
  assert.equal(candidateName(options.candidates[0]), "As in the file");
  assert.equal(candidateName(options.candidates[2]), "On the file's −Y side");
  assert.equal(priceBasis({ ...options, limits: ["Prices are the same in every orientation."] }), "Prices are the same in every orientation.");
  assert.equal(priceBasis(null), null);
  assert.equal(shadeFor("fdm", rules)?.deg, 45);
  assert.equal(shadeFor("sls", rules), null);
  assert.match(whyLine("fdm", rules), /overhang more than 45° need support/);
  assert.match(whyLine("injection_molding", rules), /1° of draft/);
  assert.match(whyLine("sls", rules), /no support/);
  assert.match(whyLine("cnc_turning", rules), /changes nothing/);
});

function issue(code: string, severity: string, message: string, extra: AnyObj = {}) {
  return { code, severity, message, fix_suggestion: null, ...extra };
}

function est(process: string, quantity: number, unit: number) {
  return { process, material: "PLA", quantity, unit_cost_usd: unit, fixed_cost_usd: 0, variable_cost_usd: unit, drivers: [], line_items: {}, dfm_ready: true, dfm_verdict: "issues", dfm_score: 0.9, dfm_blockers: [] };
}

function side(bbox: number[], fdmIssues: AnyObj[], orientation: AnyObj | null) {
  const validation = {
    filename: "l-bracket.step", file_type: "step", overall_verdict: "issues", best_process: "fdm", analysis_time_ms: 1,
    geometry: { vertices: 1, faces: 1, volume_mm3: 23760, surface_area_mm2: 1, bounding_box_mm: bbox, is_watertight: true, is_manifold: true, center_of_mass: [0, 0, 0], units: "mm" },
    segments: [], universal_issues: [], priority_fixes: [],
    process_scores: [
      { process: "fdm", score: 0.9, verdict: "issues", recommended_material: "PLA", recommended_machine: null, estimated_cost_factor: null, issues: fdmIssues },
      { process: "sla", score: 0.8, verdict: fdmIssues.length ? "fail" : "issues", recommended_material: null, recommended_machine: null, estimated_cost_factor: null, issues: fdmIssues.length ? [issue("X", "error", "blocked")] : [] },
    ],
    ...(orientation ? { orientation } : {}),
  };
  const cost = { status: "OK", material_class: "polymer", quantities: [1, 100], estimates: [est("fdm", 1, 30.25), est("fdm", 100, 22.55), est("sla", 1, 63.27), est("sla", 100, 56.34)], engine_feasibility: [] };
  return { validation, cost };
}

test("before and after a re-check: findings, methods and prices from the two results", () => {
  const rec = { rotation: [[1, 0, 0], [0, 0, -1], [0, 1, 0]], up_in_file: [0, 1, 0], label: "File +Y up", exact: true, key: "rotation:1,0,0,0,0,-1,0,1,0" };
  const b = side([60, 40, 45], [issue("OVERHANG", "warning", "28242 faces (22.6%) exceed 45° overhang threshold for fdm. Supports required.", { affected_face_count: 28242 })], null);
  const n = side([60, 45, 40], [], rec);
  assert.equal(recordOf(b.validation as never), null);
  assert.deepEqual(matOf(recordOf(n.validation as never)), [1, 0, 0, 0, 0, -1, 0, 1, 0]);
  assert.ok(same(matOf(recordOf(n.validation as never)), turned(IDENTITY, "x")));
  const cmp = compare(
    { validation: b.validation as never, cost: b.cost as never, rotation: IDENTITY },
    { validation: n.validation as never, cost: n.cost as never, rotation: matOf(rec) },
    100,
    "fdm",
  );
  const row = (what: string) => cmp.rows.find((r) => r.what === what);
  assert.deepEqual(row("Up (the file's axis)"), { what: "Up (the file's axis)", before: "+Z", now: "+Y", tone: "" });
  assert.deepEqual(row("Height"), { what: "Height", before: "45 mm", now: "40 mm", tone: "ok" });
  assert.deepEqual(row("Faces needing support"), { what: "Faces needing support", before: "28,242 faces", now: "None", tone: "ok" });
  assert.deepEqual(cmp.findings.cleared, ["28242 faces (22.6%) exceed 45° overhang threshold for fdm. Supports required."]);
  assert.deepEqual(cmp.findings.added, []);
  assert.equal(cmp.methods.before, 1);
  assert.equal(cmp.methods.now, 2);
  assert.equal(cmp.methods.changed.length, 1);
  assert.equal(cmp.methods.changed[0].tone, "ok");
  assert.ok(cmp.pricesSame);
  assert.deepEqual(cmp.pricesChanged, []);
  const dearer = side([60, 40, 45], [], rec);
  (dearer.cost.estimates[1] as { unit_cost_usd: number }).unit_cost_usd = 28.94;
  const c2 = compare({ validation: b.validation as never, cost: b.cost as never, rotation: IDENTITY }, { validation: dearer.validation as never, cost: dearer.cost as never, rotation: matOf(rec) }, 100, "fdm");
  assert.deepEqual(c2.pricesChanged, ["fdm"]);
  assert.equal(c2.rows.find((r) => /\$/.test(r.now)), undefined);
  assert.equal(row("Filament printing at 100"), undefined); // no price rows: prices don't depend on it
  // With the comparison's figures: layers, work area and the space under the support faces.
  const opts2 = {
    ...options, layer_mm: { fdm: 0.2 },
    candidates: [
      { ...cand("down-z", [0, 0, 1], 0, 45), layers: { fdm: 225 }, fits: { fdm: true } },
      { ...cand("down-y", [0, 1, 0], 0, 40), layers: { fdm: 200 }, fits: { fdm: true } },
    ],
  } as Options;
  opts2.candidates[0].support.fdm = { faces: 2, area_mm2: 2160, volume_cm3: 84.24 };
  opts2.candidates[1].support.fdm = { faces: 0, area_mm2: 0, volume_cm3: 0 };
  const c3 = compare({ validation: b.validation as never, cost: b.cost as never, rotation: IDENTITY }, { validation: n.validation as never, cost: n.cost as never, rotation: matOf(rec) }, 100, "fdm", [], opts2);
  const row3 = (what: string) => c3.rows.find((r) => r.what === what);
  assert.deepEqual(row3("Layers at 0.2 mm"), { what: "Layers at 0.2 mm", before: "225", now: "200", tone: "ok" });
  assert.deepEqual(row3("Space under them (estimate)"), { what: "Space under them (estimate)", before: "84 cm³", now: "None", tone: "ok" });
  assert.deepEqual(row3("Work area, standing this way"), { what: "Work area, standing this way", before: "Fits", now: "Fits", tone: "" });
});

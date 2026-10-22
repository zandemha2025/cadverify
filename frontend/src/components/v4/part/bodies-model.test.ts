import test from "node:test";
import assert from "node:assert/strict";
import { expandFaces, isMultiBody, closedBodies, type BodiesCheck, type PartType } from "../../../lib/verify/bodies.ts";
import { bodyRows, chipOf, metaLine, priceOf, totalOf, weldmentLines, materialNote } from "./bodies-model.ts";

// Shapes as the engine reports them (src/analysis/part_types.py on tests/part_type_cases.py).
const body = (id: number, extra: Record<string, unknown> = {}) => ({
  id,
  label: `Body ${id}`,
  name: null,
  faces: [[(id - 1) * 12, id * 12]] as [number, number][],
  face_count: 12,
  closed: true,
  voids: 0,
  volume_mm3: 27000,
  surface_area_mm2: 5400,
  bbox_mm: [30, 30, 30] as [number, number, number],
  centroid: [0, 0, 0] as [number, number, number],
  stock: { kind: "block", words: "Block 30 × 30 × 30 mm" },
  shape: "Block 30 × 30 × 30 mm",
  design: 1,
  same_as: id === 1 ? null : 1,
  copies: 2,
  ...extra,
});

const twoCubes: PartType = {
  version: 1,
  kind: "separate_bodies",
  body_count: 2,
  all_closed: true,
  summary: "This file holds 2 separate bodies that don't touch: 2 identical blocks.",
  bodies: [body(1), body(2)],
  designs: 1,
  contacts: [],
};

const twoCubesCheck: BodiesCheck = {
  filename: "two.stl",
  part_type: twoCubes,
  quantities: [1, 100],
  material_class: "polymer",
  material_basis: "default",
  designs: [
    {
      design: 1,
      bodies: [1, 2],
      copies: 2,
      status: "ok",
      verdict: "pass",
      processes: { can_make: 15, of: 21, verdicts: [] },
      by_quantity: {
        "1": { quantity_each: 2, process: "fdm", material: "PLA", unit_cost_usd: 15, per_file_usd: 30, dfm_verdict: "pass", lead_days: [2, 4] },
        "100": { quantity_each: 200, process: "mjf", material: "PA12", unit_cost_usd: 8.49, per_file_usd: 16.98, dfm_verdict: "pass", lead_days: [5, 9] },
      },
    },
  ],
  total: { per_file_usd: { "1": 30, "100": 16.98 }, basis: "the sum of the bodies, each made as its own part", complete: true },
  checks_used: 0,
};

test("a multi-body file is one the bodies sheet can read; one solid isn't", () => {
  assert.equal(isMultiBody(twoCubes), true);
  assert.equal(closedBodies(twoCubes), true);
  assert.equal(isMultiBody({ version: 1, kind: "single_solid", body_count: 1, summary: "One solid body." }), false);
  assert.equal(isMultiBody({ ...twoCubes, bodies: [body(1)] }), false);
  assert.equal(isMultiBody(null), false);
});

test("body faces expand from their runs for the 3D view", () => {
  assert.deepEqual(expandFaces([[0, 3], [10, 12]]), [0, 1, 2, 10, 11]);
  assert.deepEqual(expandFaces([[0, 100]], 5), [0, 1, 2, 3, 4]);
  assert.deepEqual(expandFaces(null), []);
});

test("before the body check runs, rows show the shapes and no prices", () => {
  const rows = bodyRows(twoCubes, null, 1);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].title, "Body 1");
  assert.equal(rows[0].sub, "Block 30 × 30 × 30 mm · 27 cm³");
  assert.deepEqual(rows[0].chip, { cls: "c-unk", label: "Not checked yet" });
  assert.equal(rows[0].price, "—");
  assert.equal(rows[1].copyOf, 1);
  assert.deepEqual(totalOf(null, 1), { value: "—", note: "check the bodies to see it" });
});

test("each body is priced as its own part, and the total is their sum", () => {
  const rows = bodyRows(twoCubes, twoCubesCheck, 100);
  assert.deepEqual(rows[0].chip, { cls: "c-ok", label: "Can make" });
  assert.equal(rows[0].price, "$8.49");
  assert.equal(rows[0].priceNote, "Nylon powder printing · PA12");
  assert.deepEqual(totalOf(twoCubesCheck, 100), { value: "$16.98", note: "sum of the bodies, each made as its own part" });
  assert.equal(metaLine(twoCubes, { ...twoCubesCheck, checked: { bodies: 2, of: 2, designs: 1 } }), "2 bodies · 1 shape · 2 of 2 checked");
});

test("a weldment shows members' stock and material, and says welding isn't priced", () => {
  const frame: PartType = {
    version: 1,
    kind: "weldment",
    body_count: 4,
    all_closed: true,
    bodies_share_edges: true,
    summary: "This file holds 4 separate bodies: likely a welded frame of 4 tubes.",
    bodies: [1, 2, 3, 4].map((i) => body(i, { shape: "Square tube 40 × 40 × 3 mm, 600 mm long", volume_mm3: 266400, design: i <= 2 ? 1 : 2, same_as: i === 2 ? 1 : i === 4 ? 3 : null })),
    designs: 2,
    joints: { count: 4, weld_length_mm_estimate: 604, words: "4 joints where members touch; about 604 mm of weld if each is welded all round (an estimate…)." },
    route: ["cut", "prep", "weld", "finish"],
  };
  const member = (design: number, ids: number[], usd: number, kg: number) => ({
    design,
    bodies: ids,
    copies: 2,
    status: "ok" as const,
    verdict: "pass" as const,
    stock: { kind: "rect_tube", words: "Square tube" },
    stock_material: { material: "Mild Steel", mass_kg: kg, usd, usd_per_kg: 1.2, density_g_cm3: 7.85, basis: "net weight × list price per kg" },
    by_quantity: { "1": { quantity_each: 2, process: "wire_edm", material: "AISI 4130", unit_cost_usd: 353.39, per_file_usd: 706.78, dfm_verdict: "pass" as const, lead_days: [7, 14] as [number, number] } },
  });
  const check: BodiesCheck = {
    filename: "frame.stl",
    part_type: frame,
    quantities: [1],
    material_class: "steel",
    material_basis: "weldment_default",
    designs: [member(1, [1, 2], 2.51, 2.091), member(2, [3, 4], 1.34, 1.115)],
    total: null,
    weldment: {
      route: ["cut", "prep", "weld", "finish"],
      members: 4,
      material_usd: 7.7,
      material_kg: 6.412,
      material_complete: true,
      cut_blanks: 0,
      cut_blanks_usd: null,
      joints: 4,
      weld_length_mm_estimate: 604,
      not_priced: ["cutting 4 tubes", "edge prep", "welding", "finishing"],
      words: "ScaleCAD doesn't price welding yet.",
    },
    checks_used: 0,
  };
  const rows = bodyRows(frame, check, 1);
  // a member is cut stock, priced by its material: never the engine's machining price for a tube
  assert.deepEqual(rows[0].chip, { cls: "c-ok", label: "Cut from stock" });
  assert.equal(rows[0].price, "$2.51");
  assert.equal(rows[0].priceNote, "material, 2.09 kg mild steel");
  assert.deepEqual(totalOf(check, 1), { value: "$7.70", note: "members’ material; welding not priced" });
  const lines = weldmentLines(check, frame);
  assert.deepEqual(lines.find((l) => l.k === "Weld length"), { k: "Weld length", v: "≈ 604 mm", note: "an estimate: each contact welded all round" });
  assert.equal(lines.find((l) => l.k === "Not priced")?.v, "cutting 4 tubes, edge prep, welding, finishing");
  assert.match(materialNote(check) ?? "", /^Priced in steel/);
});

test("body chips follow the engine's verdicts and states", () => {
  assert.deepEqual(chipOf(null, false, true), { cls: "c-unk", label: "Not checked" });
  assert.deepEqual(chipOf({ design: 1, bodies: [1], copies: 1, status: "open" }, false, true), { cls: "c-bad", label: "Not closed" });
  assert.deepEqual(chipOf({ design: 1, bodies: [1], copies: 1, status: "ok", verdict: "issues" }, false, true), { cls: "c-warn", label: "Check first" });
  assert.deepEqual(chipOf({ design: 1, bodies: [1], copies: 1, status: "ok", verdict: "fail", processes: { can_make: 0, of: 21, verdicts: [] } }, false, true), { cls: "c-bad", label: "Can’t as drawn" });
  const bolt = { design: 4, bodies: [5], copies: 6, status: "ok" as const, verdict: "issues" as const, cots: { is_cots: true, kind: "bolt", buy_price_usd: 0.75 } };
  assert.deepEqual(chipOf(bolt, false, true), { cls: "c-unk", label: "Buy" });
  assert.deepEqual(priceOf(bolt, 1, false), { value: "$0.75", note: "catalog estimate, each" });
});

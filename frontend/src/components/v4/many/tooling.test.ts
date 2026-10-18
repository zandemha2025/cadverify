import assert from "node:assert/strict";
import test from "node:test";
import { boundsOf, capCard, caveatOf, chartOf, draftOf, nearestCosted, posToQty, qtyToPos, toolingView } from "./tooling.ts";

const est = (process: string, material: string, quantity: number, unit: number, extra: Record<string, unknown> = {}) => ({
  process,
  material,
  quantity,
  unit_cost_usd: unit,
  environment_excluded: false,
  dfm_blockers: [],
  ...extra,
});

const report = {
  material_class: "aluminum",
  quantities: [10, 100],
  decision: {
    make_now_process: "cnc_turning",
    make_now_material: "6061-T6 Aluminum",
    tooling_process: "sand_casting",
    tooling_dfm_ready: false,
    crossover_qty: null,
    recommendation: {
      "10": { process: "cnc_turning", material: "6061-T6 Aluminum", unit_cost_usd: 19.54 },
      "100": { process: "cnc_turning", material: "6061-T6 Aluminum", unit_cost_usd: 13.56 },
    },
    if_redesigned: {},
    note: "Note: sand_casting requires redesign for DFM (72 sidewall faces (50.6% of sidewall area) below 3.0° draft for sand_casting.)",
  },
  estimates: [
    est("cnc_turning", "6061-T6 Aluminum", 10, 19.54),
    est("cnc_turning", "6061-T6 Aluminum", 100, 13.56),
    est("sand_casting", "A356", 10, 290.1),
    est("sand_casting", "A356", 100, 45.68),
    est("fdm", "PLA", 10, 9, { environment_excluded: true }),
  ],
} as never;

test("the tooling view reads only engine-costed points and the saved decision", () => {
  const v = toolingView(report)!;
  assert.equal(v.makeProc, "cnc_turning");
  assert.equal(v.toolProc, "sand_casting");
  assert.equal(v.ready, false);
  assert.equal(v.crossover, null);
  assert.deepEqual([...v.make.entries()], [[10, 19.54], [100, 13.56]]);
  assert.deepEqual([...v.tool.entries()], [[10, 290.1], [100, 45.68]]);
  assert.equal(v.draftDeg, 3);
  assert.equal(toolingView(null), null);
  assert.equal(toolingView({ decision: null } as never), null);
});

test("draft is read from the tooling route's own blocker first", () => {
  const r = { decision: { note: "" }, estimates: [est("injection_molding", "ABS", 10, 1, { dfm_blockers: ["16 sidewall faces (100.0% of sidewall area) below 1.0° draft for injection_molding."] })] } as never;
  assert.equal(draftOf(r, "injection_molding"), 1);
  assert.equal(draftOf(r, null), null);
});

test("the quantity slider is log scale and snaps to the nearest costed quantity", () => {
  assert.equal(posToQty(0), 1);
  assert.equal(posToQty(1000), 10000);
  assert.equal(posToQty(500), 100);
  assert.equal(qtyToPos(100), 500);
  assert.equal(nearestCosted([10, 100], 30), 10);
  assert.equal(nearestCosted([10, 100], 40), 100);
  assert.equal(nearestCosted([], 40), null);
});

test("chart paths pass through the real points only; no crossover line without a crossover", () => {
  const c = chartOf(toolingView(report)!, 100);
  assert.equal(c.makeDots.length, 2);
  assert.equal(c.toolDots.length, 2);
  assert.match(c.makePath, /^M\S+ \S+ L\S+ \S+$/);
  assert.equal(c.xLine, null);
});

test("capability cards name the machine, the material or the measured bound", () => {
  const machines = [{ id: "1", name: "Haas VF-2", process: "cnc_3axis", capabilities: { x: 762, y: 406, z: 508 } }, { id: "2", name: "Haas ST-20", process: "cnc_turning" }];
  const mat = capCard({ acquisition: { kind: "upgrade", process: "cnc_3axis", gate: "material", spec: { qualify_materials: ["PEEK"] } }, parts_unlocked: 1, stale: false, stale_parts: 0 }, machines);
  assert.equal(mat.title, "Qualify Haas VF-2 for PEEK");
  assert.equal(mat.kind, "material");
  const text = "Part minimum width is at least 268.814272mm > smallest chamber span 254mm. This necessary bound is not a machine specification; verify the full XYZ setup.";
  const env = capCard({ acquisition: { kind: "upgrade", process: "cnc_turning", gate: "envelope", spec: { recorded_bounds: [text] } }, parts_unlocked: 1, stale: true, stale_parts: 1 }, machines);
  assert.equal(env.title, "Lathe wider than 269 mm");
  assert.deepEqual(env.bounds, { need: 268.814272, have: 254 });
  assert.equal(env.caveat, "This necessary bound is not a machine specification; verify the full XYZ setup.");
  const add = capCard({ acquisition: { kind: "acquire", process: "mjf", gate: null, spec: { summary: "a nylon printer" } }, parts_unlocked: 3, stale: false, stale_parts: 0 }, machines);
  assert.equal(add.title, "Add Nylon printing, MJF: a nylon printer");
  assert.equal(boundsOf("nothing here"), null);
  assert.equal(caveatOf("One sentence only"), null);
});

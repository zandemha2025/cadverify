import assert from "node:assert/strict";
import test from "node:test";
import { bucketDef, costLabel, orderedBuckets, reasonOf, wallTooThin, type MakeRow } from "./makeability.ts";

const row = (o: Partial<MakeRow> & { verdict?: string | null; gap?: unknown }): MakeRow =>
  ({
    part_key: "k",
    filename: "p.stl",
    recommended_route: { process: "cnc_3axis", material: "6061-T6 Aluminum" },
    unit_cost: null,
    ...o,
    makeability: { verdict: o.verdict === undefined ? "makeable_in_house" : o.verdict, stale: false, gap: (o.gap ?? null) as never },
  }) as MakeRow;

const machines = [
  { id: "1", name: "Haas VF-2", process: "cnc_3axis" },
  { id: "2", name: "Haas ST-20", process: "cnc_turning" },
];

test("unknown bucket keys get their own neutral bucket, ordered after the known four", () => {
  const d = bucketDef("needs_design_change");
  assert.equal(d.label, "Needs design change");
  assert.equal(d.tone, "unk");
  assert.equal(d.primary, true);
  const keys = orderedBuckets(["makeable_in_house", "needs_design_change"], { total: 3, stale_count: 0, makeable_in_house: 1, needs_design_change: 2 });
  assert.deepEqual(keys, ["makeable_in_house", "makeable_outside", "needs_capability", "not_makeable", "needs_design_change", "unknown", "geometry_invalid"]);
  assert.equal(bucketDef("needs_capability", { severalChanges: true }).label, "Capability change");
});

test("reasons read the route, the gap and the DFM blocker, never invent one", () => {
  assert.equal(reasonOf(row({}), machines), "Haas VF-2 · 6061-T6 Aluminum");
  const env = row({ verdict: "makeable_not_on_owned", gap: { process: "cnc_turning", gap: [{ gate: "envelope", have: 254, need: 268.8, human: "long text. more" }] } });
  assert.equal(reasonOf(env, machines), "Haas ST-20 · needs at least 269 mm; Haas ST-20 takes 254 mm");
  const mat = row({ verdict: "makeable_not_on_owned", gap: { process: "cnc_3axis", gap: [{ gate: "material", human: "not qualified for PEEK" }] } });
  assert.equal(reasonOf(mat, machines), "Haas VF-2 · not qualified for PEEK");
  const dfm = row({ verdict: "not_makeable", gap: { gate: "dfm", gap: [{ gate: "dfm", axis: "THIN_WALL", human: "11 faces under 0.8 mm. Thinnest 0.6 mm." }] } });
  assert.equal(reasonOf(dfm, machines), "11 faces under 0.8 mm");
  assert.equal(wallTooThin(dfm), true);
  const withheld = row({ verdict: "not_makeable", unit_cost: { qty: 10, usd: null, withheld: true, withheld_reason: "24 faces (100.0%) below 1.5mm min wall for ded. Thinnest: 0.5mm." } });
  assert.equal(reasonOf(withheld), "24 faces (100.0%) below 1.5mm min wall for ded");
  assert.equal(wallTooThin(withheld), true);
  assert.equal(reasonOf(row({ verdict: null })), "Not checked against your machines");
  assert.equal(reasonOf(row({ verdict: "something_new" })), "Something new");
});

test("cost labels show the quantity and say withheld, never a made-up number", () => {
  assert.equal(costLabel(row({ unit_cost: { qty: 10, usd: 19.54, withheld: false } })), "$19.54 at 10");
  assert.equal(costLabel(row({ unit_cost: { qty: 1, usd: 30, withheld: false } })), "$30.00");
  assert.equal(costLabel(row({ unit_cost: { qty: 10, usd: null, withheld: true } })), "Withheld");
  assert.equal(costLabel(row({ unit_cost: null })), "—");
});

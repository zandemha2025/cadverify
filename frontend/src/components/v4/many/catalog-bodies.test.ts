import test from "node:test";
import assert from "node:assert/strict";
import { bodyLine, filterRows, type BoardRow } from "./catalog-model.ts";

const row = (extra: Partial<BoardRow>): BoardRow =>
  ({
    item_id: "IT1:1",
    filename: "frame - body 1.stl",
    part_number: null,
    status: "completed",
    part_key: "a".repeat(64),
    analysis_id: "AN1",
    cost_decision_id: null,
    quantity: 20,
    quantity_source: "run",
    verdict: null,
    bucket: "not_sorted",
    reason: "Weldment member: Square tube 40 × 40 × 3 mm, 600 mm long. Welding isn't priced yet",
    route: null,
    material: { declared: null, class: null, note: null, name: "Mild Steel", mass_kg_each: 2.091, mass_basis: null },
    hours_each: null,
    hours_total: null,
    mass_kg_total: 41.82,
    unit_cost_usd: null,
    total_cost_usd: null,
    price_withheld: "welding isn't priced yet",
    machine_rate_usd: null,
    marginal: false,
    capability: null,
    cheaper_outside: null,
    duration_ms: null,
    error: null,
    ...extra,
  }) as BoardRow;

test("a body of a split file says which file and how many per file", () => {
  const r = row({ body: { file: "frame.stl", file_key: "f".repeat(64), kind: "weldment", ids: [1, 2], copies: 2, of: 4, shape: "Square tube 40 × 40 × 3 mm, 600 mm long", name: null } });
  assert.equal(bodyLine(r), "Bodies 1, 2 of 4 in frame.stl · 2 per file · Square tube 40 × 40 × 3 mm, 600 mm long");
  assert.equal(bodyLine(row({ body: { file: "as1.step", file_key: null, kind: "assembly", ids: [5], copies: 1, of: 18, shape: null, name: "bolt" } })), "bolt of 18 in as1.step");
  assert.equal(bodyLine(row({})), null);
});

test("the board's search finds a split file's bodies by their own names", () => {
  const rows = [row({ filename: "frame - body 1.stl" }), row({ filename: "cube.stl", item_id: "IT2" })];
  assert.deepEqual(filterRows(rows, "all", "frame").map((r) => r.filename), ["frame - body 1.stl"]);
});

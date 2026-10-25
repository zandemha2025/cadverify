import { test } from "node:test";
import assert from "node:assert/strict";

const { findParts, findRecords, looksLikeQuestion, searchWords } = await import("./palette-search.ts");

const parts = [
  { mesh_hash: "bcbaa8cdfb63", filename: "plate-with-boss.step", program: "Wellhead", specs: ["Finish: Anodize, Type II, Ra 1.6 µm", "Inspection: First article inspection, AS9102", "Supplier must hold: AS9100", "General tolerance: ±0.1 mm"] },
  { mesh_hash: "59407484c8e0", filename: "bored-block-mm.iges", program: null, specs: [] },
];

test("search finds a part by name first, and by a spec it declares (buyer-06, buyer-16)", () => {
  const plate = findParts(parts, "plate");
  assert.equal(plate[0].label, "plate-with-boss.step");
  assert.equal(plate[0].href, "/app/part/bcbaa8cdfb63");
  assert.match(plate[0].sub, /^Program Wellhead · Finish: Anodize/);
  for (const q of ["anodize", "AS9100", "first article", "tolerance", "±0.1"]) {
    const hit = findParts(parts, q);
    assert.equal(hit.length, 1, q);
    assert.equal(hit[0].href, "/app/part/bcbaa8cdfb63?lens=use", q);
  }
  assert.equal(findParts(parts, "anodize")[0].sub, "Finish: Anodize, Type II, Ra 1.6 µm");
  assert.deepEqual(findParts(parts, "titanium"), []);
  assert.deepEqual(findParts(parts, ""), []);
});

test("a record row names the short id the list shows and which one is the latest", () => {
  const recs = [
    { id: "01M5J2B8XXXXXXXXXXXX90ZH0C", filename: "plate-with-boss.step", created_at: "2026-10-22T15:09:00Z" },
    { id: "01M5J20JXXXXXXXXXXXXBE1VCV", filename: "plate-with-boss.step", created_at: "2026-10-22T14:50:00Z", approval_status: "approved" },
  ];
  const rows = findRecords(recs, "plate");
  assert.equal(rows[0].sub, "Cost record #90ZH0C · Oct 22 · latest for this file · not reviewed");
  assert.equal(rows[1].sub, "Cost record #BE1VCV · Oct 22 · approved");
  assert.equal(findRecords(recs, "#be1vcv")[0].label, "plate-with-boss.step");
});

test("search offers to answer only where a page answers; a question elsewhere is told what search does (op-14)", () => {
  assert.deepEqual(searchWords([]), { button: "Search parts and tools", box: "Search parts, records, machines and tools" });
  assert.deepEqual(searchWords([{ answer: undefined }, {}]).button, "Search parts and tools");
  // The part page registers answers from its own results.
  assert.equal(searchWords([{ answer: { text: "Haas VF-2 ($26.17 at 500)", source: "machine fit" } }]).button, "Search, or ask about this part");
  assert.equal(looksLikeQuestion("which of my machines would be overloaded if we make these parts"), true);
  assert.equal(looksLikeQuestion("is it cheaper to buy?"), true);
  assert.equal(looksLikeQuestion("machine capacity overloaded"), false);
  assert.equal(looksLikeQuestion("plate"), false);
});

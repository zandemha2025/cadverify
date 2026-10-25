import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { openingQty } from "./model.ts";

// The backend's catalog_service.opening_qty reads the same cases, so the parts list, the
// catalog board and the part page open at one quantity (ce-19, op-08).
const fixture = JSON.parse(readFileSync(new URL("../../../../../backend/tests/fixtures/opening_qty_cases.json", import.meta.url), "utf8")) as {
  cases: { quantities: number[]; yearly: number | null; opens: number | null }[];
};

test("the part opens at the quantity the backend opens it at", () => {
  assert.ok(fixture.cases.length >= 10);
  for (const c of fixture.cases) {
    // null: nothing priced, so no quantity to open at.
    const opens = c.quantities.length ? openingQty(c.quantities, c.yearly) : null;
    assert.equal(opens, c.opens, JSON.stringify(c));
  }
});

import test from "node:test";
import assert from "node:assert/strict";
import { partSearch } from "./url-state.ts";

test("the lens and the priced quantity go in the URL, and nothing else changes", () => {
  assert.equal(partSearch("", { lens: "make", q: 10, qs: [1, 10, 100] }), "?lens=make&qty=10");
  assert.equal(partSearch("?problem=open&method=fdm", { lens: "cost", q: 1000, qs: [10, 1000] }), "?problem=open&method=fdm&lens=cost&qty=1000");
  assert.equal(partSearch("?lens=cost&qty=10", { lens: "decide", q: 100, qs: [10, 100] }), "?lens=decide&qty=100");
});

test("a quantity the record didn't price isn't written (it would read as a request on reopen)", () => {
  assert.equal(partSearch("?qty=250", { lens: "cost", q: 250, qs: [10, 100] }), "?lens=cost");
  assert.equal(partSearch("", { lens: "make", q: 10, qs: [] }), "?lens=make", "an analysis-only part keeps its lens");
});

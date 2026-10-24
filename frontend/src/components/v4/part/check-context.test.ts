import test from "node:test";
import assert from "node:assert/strict";
import { checkContext, checkHref, contextLine, handoverHref, hasContext } from "./check-context.ts";

const K = "59407484c8e0db62203458be0865d160e763d6dce236b5e6fad0b6924746f588";

test("Check another part carries the cost breakdown's material and quantity", () => {
  assert.equal(checkHref({ material: "aluminum", qty: 50 }), "/app/check?material=aluminum&qty=50");
  assert.equal(checkHref({ material: "polymer" }), "/app/check?material=polymer");
  assert.equal(checkHref({}), "/app/check");
  assert.equal(checkHref({ material: "unobtanium", qty: 0 }), "/app/check", "only what the check can use goes in");
  assert.equal(checkHref({ issue: "insufficient_draft|faces" }), "/app/check?issue=INSUFFICIENT_DRAFT");
});

test("the check page reads the context back, and drops what it can't use", () => {
  assert.deepEqual(checkContext("?material=stainless&qty=5000"), { material: "stainless", qty: 5000, issue: null });
  assert.deepEqual(checkContext("?material=wood&qty=2.5"), { material: null, qty: null, issue: null });
  assert.deepEqual(checkContext("?qty=20000000"), { material: null, qty: null, issue: null }, "over the engine's limit");
  assert.deepEqual(checkContext("?issue=INSUFFICIENT_DRAFT%7Cfaces&issue_evidence=x"), { material: null, qty: null, issue: "INSUFFICIENT_DRAFT" });
  assert.equal(hasContext(checkContext("")), false);
  assert.equal(hasContext(checkContext("?qty=50")), true);
});

test("the start screen says what the next check is priced with", () => {
  assert.equal(contextLine({ material: "aluminum", qty: 50, issue: null }), "Aluminum · 50 parts");
  assert.equal(contextLine({ material: null, qty: 1, issue: null }), "1 part");
  assert.equal(contextLine({ material: "stainless", qty: 5000, issue: null }), "Stainless steel · 5,000 parts");
  assert.equal(contextLine({ material: null, qty: null, issue: "THIN_WALL" }), null);
});

test("the check hands over on Cost at the carried quantity, or on the carried problem", () => {
  assert.equal(handoverHref(K, { material: "steel", qty: 50, issue: null }, null), `/app/part/${K}?lens=cost&qty=50`);
  assert.equal(handoverHref(K, { material: "steel", qty: null, issue: null }, null), `/app/part/${K}`);
  assert.equal(handoverHref(K, { material: null, qty: 50, issue: "INSUFFICIENT_DRAFT" }, "draft"), `/app/part/${K}?problem=draft`);
});

import test from "node:test";
import assert from "node:assert/strict";
import { R, sectionOf } from "../routes.ts";
import { LEGACY_WORKBENCH, legacyWorkbenchTarget, tabOf, wbHref } from "./cost-url.ts";

const P = "59407484c8e0db62203458be0865d160e763d6dce236b5e6fad0b6924746f588";

test("the cost breakdown lives under its part, beside the part's history", () => {
  assert.equal(R.cost(P), `/app/part/${P}/cost`);
  assert.equal(wbHref(null, P), `/app/part/${P}/cost`);
  assert.equal(wbHref("glass", P), `/app/part/${P}/cost?tab=lines`);
  assert.equal(wbHref("decision", P, { q: 500, proc: null }), `/app/part/${P}/cost?tab=summary&q=500`);
  assert.equal(wbHref("glass", P, { decision: "01M5", proc: "cnc_3axis", q: 50 }), `/app/part/${P}/cost?tab=lines&decision=01M5&proc=cnc_3axis&q=50`);
  assert.equal(wbHref("history", "a b/c"), "/app/part/a%20b%2Fc/cost?tab=history", "the key is one path segment");
  assert.equal(sectionOf(R.cost(P)), "parts");
});

test("tab names: the current ones and the older spellings open the same view", () => {
  assert.equal(tabOf("summary"), "decision");
  assert.equal(tabOf("decision"), "decision");
  assert.equal(tabOf("lines"), "glass");
  assert.equal(tabOf("glass"), "glass");
  assert.equal(tabOf("dfm"), "routing");
  assert.equal(tabOf("routing"), "routing");
  assert.equal(tabOf("nonsense"), null);
  assert.equal(tabOf(null), null);
});

test("old /app/make/workbench links redirect to the part's cost breakdown with every other parameter kept", () => {
  assert.equal(LEGACY_WORKBENCH, "/app/make/workbench");
  assert.equal(
    legacyWorkbenchTarget(new URLSearchParams(`tab=decision&part=${P}&decision=01M56P3X598SYXRY84VKKZAEQ1`)),
    `/app/part/${P}/cost?tab=decision&decision=01M56P3X598SYXRY84VKKZAEQ1`,
  );
  assert.equal(legacyWorkbenchTarget(new URLSearchParams(`part=${P}`)), `/app/part/${P}/cost`);
  assert.equal(legacyWorkbenchTarget({ part: P, tab: "glass", proc: "mjf", q: "50", lens: "cost" }), `/app/part/${P}/cost?tab=glass&proc=mjf&q=50&lens=cost`);
  assert.equal(legacyWorkbenchTarget({ part: P, tab: "routing", issue: "INSUFFICIENT_DRAFT|faces" }), `/app/part/${P}/cost?tab=routing&issue=INSUFFICIENT_DRAFT%7Cfaces`, "the DFM tab still opens the part's problems from there");
  assert.equal(legacyWorkbenchTarget({ tab: "lines" }), null, "no part: the old page decides");
  assert.equal(legacyWorkbenchTarget({ part: "  " }), null);
});

import assert from "node:assert/strict";
import test from "node:test";
import { twoStepHref } from "./href.ts";

test("the code step keeps where the sign-in was going", () => {
  assert.equal(twoStepHref("/app/parts?x=1"), "/login/two-step?next=%2Fapp%2Fparts%3Fx%3D1");
  assert.equal(twoStepHref(null), "/login/two-step");
  assert.equal(twoStepHref(""), "/login/two-step");
});

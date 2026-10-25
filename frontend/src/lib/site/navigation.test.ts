import { test } from "node:test";
import assert from "node:assert/strict";

const { SIGNUP_HREF, signupHref } = await import("./navigation.ts");

test("Try free opens Create account, not Sign in", () => {
  assert.equal(SIGNUP_HREF, "/signup");
  assert.equal(signupHref(), "/signup");
  assert.equal(signupHref("/app/many?new=1"), "/signup?next=%2Fapp%2Fmany%3Fnew%3D1");
});

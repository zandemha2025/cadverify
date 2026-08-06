import assert from "node:assert/strict";
import test from "node:test";

import { publicPasswordSignupEnabled } from "./public-signup.ts";

test("signup UI accepts the same explicit truthy values as the API", () => {
  for (const value of ["1", "true", "TRUE", "yes", "on"]) {
    assert.equal(publicPasswordSignupEnabled(value, "dev"), true);
  }
});

test("signup defaults open only for local builds and fails closed on unknown values", () => {
  assert.equal(publicPasswordSignupEnabled(undefined, "dev"), true);
  assert.equal(publicPasswordSignupEnabled(undefined, "release-sha"), false);
  assert.equal(publicPasswordSignupEnabled("false", "dev"), false);
  assert.equal(publicPasswordSignupEnabled("unexpected", "dev"), false);
});

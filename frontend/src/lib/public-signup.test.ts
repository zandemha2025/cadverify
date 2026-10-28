import assert from "node:assert/strict";
import test from "node:test";

import { publicPasswordSignupEnabled, siteSignupMethod } from "./public-signup.ts";

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


test("marketing signup follows enabled authentication methods", () => {
  assert.equal(siteSignupMethod("", true), "password");
  assert.equal(siteSignupMethod("turnstile-key", true), "magic");
  assert.equal(siteSignupMethod("turnstile-key", false), "magic");
  assert.equal(siteSignupMethod("", false), "managed");
});

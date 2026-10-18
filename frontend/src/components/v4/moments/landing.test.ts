import { test } from "node:test";
import assert from "node:assert/strict";

// routes.ts files are plain constants; import through the .ts paths for node --test.
const { v4Landing, V4_HOME, V4_SIGNUP_HOME } = await import("./landing.ts");

test("today's default landing becomes Home; other server paths stay", () => {
  assert.equal(V4_HOME, "/app");
  assert.equal(V4_SIGNUP_HOME, "/app?welcome=1");
  assert.equal(v4Landing("/verify"), "/app");
  assert.equal(v4Landing("/verify?x=1"), "/app");
  assert.equal(v4Landing("/settings/developer?new=1&prefix=cv_ab"), "/settings/developer?new=1&prefix=cv_ab");
  assert.equal(v4Landing("/verifyx"), "/verifyx");
});

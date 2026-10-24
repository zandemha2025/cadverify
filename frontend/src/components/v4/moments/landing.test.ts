import { test } from "node:test";
import assert from "node:assert/strict";

// routes.ts files are plain constants; import through the .ts paths for node --test.
const { afterSignup, v4Landing, V4_HOME, V4_SIGNUP_HOME } = await import("./landing.ts");

test("today's default landing becomes Home; other server paths stay", () => {
  assert.equal(V4_HOME, "/app");
  assert.equal(V4_SIGNUP_HOME, "/app");
  assert.equal(v4Landing("/verify"), "/app");
  assert.equal(v4Landing("/verify?x=1"), "/app");
  assert.equal(v4Landing("/settings/developer?new=1&prefix=cv_ab"), "/settings/developer?new=1&prefix=cv_ab");
  assert.equal(v4Landing("/verifyx"), "/verifyx");
});

test("a new account goes to the phone check when sign-up sent a code or a part waits, keeping where it was going", () => {
  assert.equal(afterSignup({ next: "/app", phone: null, held: false }), "/app");
  assert.equal(afterSignup({ next: "/app", phone: "sent", held: false }), "/app/phone?next=%2Fapp");
  assert.equal(afterSignup({ next: "/app/many?new=1", phone: "failed", held: false }), "/app/phone?next=%2Fapp%2Fmany%3Fnew%3D1");
  assert.equal(afterSignup({ next: "/app", phone: null, held: true }), "/app/phone?next=%2Fapp");
});

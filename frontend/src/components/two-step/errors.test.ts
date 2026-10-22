import assert from "node:assert/strict";
import test from "node:test";

const { twoStepError, errorCode } = await import("./errors.ts");

test("the server's words reach the page whether the error body is flat or wrapped", () => {
  const flat = { code: "two_step_code_wrong", message: "That code didn't match. Use the newest code in your authenticator app." };
  assert.equal(twoStepError(400, flat, "fallback"), flat.message);
  assert.equal(twoStepError(400, { detail: flat }, "fallback"), flat.message);
  assert.equal(errorCode(flat), "two_step_code_wrong");
  assert.equal(errorCode({ detail: flat }), "two_step_code_wrong");
  const locked = { code: "two_step_locked", message: "Too many wrong codes. Code entry for this account is paused. Try again in 15 minutes." };
  assert.equal(twoStepError(429, locked, "fallback"), locked.message);
  assert.equal(twoStepError(400, {}, "fallback"), "fallback");
  assert.equal(twoStepError(502, { message: "boom" }, "fallback"), "The sign-in service couldn't finish this. Try again.");
});

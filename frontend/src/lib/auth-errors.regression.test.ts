import { test } from "node:test";
import assert from "node:assert/strict";
import { authErrorMessage } from "./api-recovery.ts";

// Regression: PROD-005 — outages were blamed on credentials or expired links.
// Found by /qa on 2026-09-29; outputs/production-audit-20260929/findings.md.
test("auth failures distinguish outages and throttling from rejected credentials", () => {
  for (const fallback of ["Invalid email or password.", "Magic link invalid or expired."]) {
    for (const status of [500, 502, 503, 504]) {
      const message = authErrorMessage(status, {}, fallback);
      assert.match(message, /service.*could not.*try again/i);
      assert.notEqual(message, fallback);
    }
    assert.match(authErrorMessage(429, {}, fallback), /too many.*try again/i);
    assert.equal(authErrorMessage(401, {}, fallback), fallback);
  }
  assert.equal(authErrorMessage(403, { detail: "Password sign-in is disabled." }, "Failed"), "Password sign-in is disabled.");
  assert.equal(authErrorMessage(422, { detail: [{ msg: "Enter a valid email." }] }, "Failed"), "Enter a valid email.");
  assert.equal(authErrorMessage(422, { detail: [{ type: "string_too_long", loc: ["body", "password"], msg: "String should have at most 128 characters" }] }, "Failed"), "String should have at most 128 characters");
  assert.equal(authErrorMessage(400, { detail: { message: { malformed: true } } }, "Failed"), "Failed");
  assert.equal(authErrorMessage(503, { detail: { message: "Authentication is temporarily unavailable." } }, "Failed"), "Authentication is temporarily unavailable.");
});

import assert from "node:assert/strict";

export function assertWeakPasswordRejection(status, body) {
  assert.equal(status, 400);
  assert.equal(body?.code, "weak_password");
  assert.equal(body?.message, "Password must be at least 8 characters.");
}

export function isExpectedSignupConsoleError(error, resourceUrl) {
  return error.sourceUrl === resourceUrl &&
    error.text === "Failed to load resource: the server responded with a status of 400 (Bad Request)";
}

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  apiRecoveryMessage,
  networkRecoveryMessage,
} from "./api-recovery.ts";

for (const [status, action] of [
  [401, /sign in again/i],
  [403, /organization admin/i],
  [404, /return to the list/i],
  [409, /refresh the page/i],
  [422, /review the input/i],
  [429, /try again in 12 seconds/i],
  [500, /try again/i],
] as const) {
  test(`${status} recovery copy names a concrete next action`, () => {
    const message = apiRecoveryMessage({
      status,
      payload: { detail: { message: "Structured backend detail" } },
      resource: "batch",
      retryAfter: status === 429 ? "12" : null,
    });
    assert.match(message, action);
    assert.doesNotMatch(message, /\[object Object\]/);
  });
}

test("422 preserves a structured validation detail before the recovery action", () => {
  assert.equal(
    apiRecoveryMessage({
      status: 422,
      payload: { detail: [{ msg: "ZIP archive contains no supported CAD files" }] },
      resource: "batch",
    }),
    "ZIP archive contains no supported CAD files. Review the input and try again.",
  );
});

test("network recovery copy does not imply that data was deleted", () => {
  const message = networkRecoveryMessage("design");
  assert.match(message, /check your network/i);
  assert.match(message, /refresh the saved list/i);
  assert.doesNotMatch(message, /lost|deleted/i);
});

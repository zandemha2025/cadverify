import { test } from "node:test";
import assert from "node:assert/strict";

import {
  apiProblemDetail,
  apiResourceFromUrl,
  apiRecoveryMessage,
  networkRecoveryMessage,
  isQuotaErrorMessage,
  isLifetimeQuotaErrorMessage,
} from "./api-recovery.ts";

for (const [status, code, detail] of [
  [429, "org_validation_cap_exceeded", "this organization has reached its cap of 100 validations in total"],
  [403, "user_validation_cap_exceeded", "this account has used its 100 trial checks"],
  [429, "org_quota_exceeded", "daily analyses cap reached; it resets on a rolling ~24h window"],
] as const) {
  test(`${code} retains allowance details without promising an immediate retry`, () => {
    for (const payload of [{ code, message: detail }, { detail: { code, message: detail } }]) {
      const message = apiRecoveryMessage({ status, payload, resource: "verification", retryAfter: "60" });
      assert.match(message, /verification allowance used up/i);
      assert.ok(message.includes(detail));
      assert.match(message, /contact.*team/i);
      assert.doesNotMatch(message, /try again in|temporarily busy|permission|too many/i);
    }
  });
}

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

test("structured backend detail is extracted without object coercion", () => {
  assert.equal(
    apiProblemDetail({ detail: { code: "server_busy", message: "server is at capacity, retry shortly" } }),
    "server is at capacity, retry shortly",
  );
});

test("specific 503 recovery copy is preserved for queue failures", () => {
  assert.equal(
    apiRecoveryMessage({
      status: 503,
      payload: {
        detail: {
          code: "DESIGN_ENQUEUE_FAILED",
          message: "Design generation is temporarily unavailable. Retry shortly.",
        },
      },
      resource: "design",
    }),
    "Design generation is temporarily unavailable. Retry shortly.",
  );
});

for (const [url, resource] of [
  ["/api/v1/validate/cost", "verification"],
  ["/api/v1/cost-decisions/01TEST", "decision"],
  ["http://localhost:3000/api/v1/analyses?limit=8", "analysis"],
  ["/api/v1/batches/01TEST", "batch"],
  ["/api/v1/organizations/current", "organization"],
  ["/api/v1/api-keys", "API key"],
  ["/api/v1/invitations/accept", "invitation"],
  ["/api/v1/reconstruct", "reconstruction"],
  ["/api/v1/unknown-surface", "request"],
] as const) {
  test(`API URL ${url} maps recovery copy to ${resource}`, () => {
    assert.equal(apiResourceFromUrl(url), resource);
  });
}

test("rolling allowances retain later retry while lifetime caps do not", () => {
  for (const payload of [
    { code: "org_quota_exceeded", message: "Daily cap; rolling ~24h window" },
    { code: "org_validation_cap_exceeded", message: "100 validations in the trailing 7 days" },
    { detail: { code: "user_validation_cap_exceeded", window_days: 30, message: "Trial checks used" } },
  ]) {
    const message = apiRecoveryMessage({ status: 403, payload, resource: "verification" });
    assert.equal(isQuotaErrorMessage(message), true);
    assert.equal(isLifetimeQuotaErrorMessage(message), false);
    assert.match(message, /retry after the rolling allowance becomes available/i);
  }
  const lifetime = apiRecoveryMessage({ status: 429, resource: "verification",
    payload: { code: "org_validation_cap_exceeded", window_days: 0, message: "100 checks in total" } });
  assert.equal(isLifetimeQuotaErrorMessage(lifetime), true);
  assert.doesNotMatch(lifetime, /retry|for now/i);
});

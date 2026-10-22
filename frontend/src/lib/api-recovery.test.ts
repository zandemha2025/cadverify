import { test } from "node:test";
import assert from "node:assert/strict";

import {
  isPhoneVerificationMessage,
  apiProblemDetail,
  apiResourceFromUrl,
  apiRecoveryMessage,
  networkRecoveryMessage,
  isQuotaErrorMessage,
  isLifetimeQuotaErrorMessage,
  refusalDetail,
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
      // A person's own allowance carries its own next step (upgrade); shared
      // organization allowances still point at the people who manage them.
      if (code === "user_validation_cap_exceeded") assert.doesNotMatch(message, /administrator/i);
      else assert.match(message, /contact.*team/i);
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

test("free and Pro allowances read as one short next step", () => {
  const free = apiRecoveryMessage({ status: 403, resource: "verification", payload: { detail: {
    code: "user_validation_cap_exceeded", plan: "trial", tier: "personal", window_days: 0, resets_at: null,
    message: "Your 3 free checks are used or in progress. Upgrade to Pro to keep checking. Saved results stay available." } } });
  assert.equal(free, "Verification allowance used up. Your 3 free checks are used or in progress. Upgrade to Pro to keep checking. Saved results stay available.");
  assert.equal(isLifetimeQuotaErrorMessage(free), true);
  const pro = apiRecoveryMessage({ status: 403, resource: "verification", payload: { detail: {
    code: "user_validation_cap_exceeded", plan: "pro", window_days: 0, resets_at: "2026-11-17T00:00:00+00:00",
    message: "You've used this month's 50 Pro checks. They reset on November 17. Saved results stay available." } } });
  assert.match(pro, /^Verification allowance used up for now\. You've used this month's 50 Pro checks/);
  assert.equal(isLifetimeQuotaErrorMessage(pro), false);
  assert.equal(isQuotaErrorMessage(pro), true);
  assert.doesNotMatch(pro, /retry after the rolling/i);
});

test("phone verification is its own recovery, not a permission error", () => {
  const message = apiRecoveryMessage({ status: 403, resource: "verification", payload: { detail: {
    code: "phone_verification_required", message: "Verify your phone number to start your free checks. We send one text with a code." } } });
  assert.equal(isPhoneVerificationMessage(message), true);
  assert.doesNotMatch(message, /permission|admin/i);
  assert.equal(isQuotaErrorMessage(message), false);
});

test("a refused STEP probe out of checks reads as out of checks, not as an unreadable file", () => {
  const quota = { detail: { code: "user_validation_cap_exceeded", message: "Your 3 free checks are used or in progress. Upgrade to Pro to keep checking. Saved results stay available.", cap: 3, remaining: 0, window_days: 0 } };
  assert.ok(isQuotaErrorMessage(refusalDetail(403, quota, "verification")));
  const phone = { detail: { code: "phone_verification_required", message: "Verify your phone number to start your free checks. We send one text with a code." } };
  assert.ok(isPhoneVerificationMessage(refusalDetail(403, phone, "verification")));
  const bad = { detail: { code: "unreadable_step", message: "The STEP file has no solids." } };
  assert.equal(refusalDetail(422, bad, "verification"), "The STEP file has no solids.");
});

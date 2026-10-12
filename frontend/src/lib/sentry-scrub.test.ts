import assert from "node:assert/strict";
import test from "node:test";
import { scrubSentryEvent } from "./sentry-scrub.ts";

test("password changes never send either credential to telemetry", () => {
  const event = {
    request: { data: { current_password: "OldCredential123", password: "NewCredential456" } },
    tags: { page: "security" },
  };
  const scrubbed = scrubSentryEvent(event);
  assert.equal(JSON.stringify(scrubbed).includes("Credential"), false);
  assert.deepEqual(scrubbed.tags, event.tags);
  assert.equal(event.request.data.current_password, "OldCredential123");
});

test("password reset links and POST bodies are scrubbed from telemetry", () => {
  const token = "reset-proof-test-sentinel";
  const event = { request: { url: `https://scalecad.ai/reset-password#token=${token}`, data: { token, password: "ResetPassword456" } } };
  const scrubbed = JSON.stringify(scrubSentryEvent(event));
  assert.equal(scrubbed.includes(token), false);
  assert.equal(scrubbed.includes("ResetPassword456"), false);
});

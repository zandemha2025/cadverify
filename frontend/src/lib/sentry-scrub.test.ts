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

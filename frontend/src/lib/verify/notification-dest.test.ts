import assert from "node:assert/strict";
import test from "node:test";

import {
  notificationHref,
  notificationScreenFromSearch,
} from "./notification-dest.ts";

test("notification destinations produce stable Verify deep links", () => {
  assert.equal(notificationHref("records"), "/verify?screen=records");
  assert.equal(notificationHref("calibration"), "/verify?screen=calibration");
  assert.equal(notificationHref("verify"), "/verify?screen=verify");
});

test("cost notifications open their exact source record with a safe fallback", () => {
  const source = { source_type: "cost_decision", source_id: "01M3R5PQHVPT6BE584E0R6J1J8" };
  assert.equal(notificationHref("records", source), `/cost-decisions/${source.source_id}`);
  assert.equal(notificationHref("records", { ...source, source_id: "../settings" }), "/verify?screen=records");
  assert.equal(notificationHref("records", { ...source, source_type: "unknown" }), "/verify?screen=records");
  assert.equal(notificationHref("calibration", { source_type: "rate_card" }), "/verify?screen=calibration");
});

test("Verify accepts only declared notification screen destinations", () => {
  assert.equal(notificationScreenFromSearch("?screen=records"), "records");
  assert.equal(
    notificationScreenFromSearch("?screen=calibration"),
    "calibration",
  );
  assert.equal(notificationScreenFromSearch("?screen=verify"), "verify");
  assert.equal(notificationScreenFromSearch("?screen=home"), null);
  assert.equal(notificationScreenFromSearch("?screen=records%2F.."), null);
  assert.equal(notificationScreenFromSearch(""), null);
});

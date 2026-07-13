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

import assert from "node:assert/strict";
import { test } from "node:test";

import { batchActivityCopy } from "./batch-progress-copy.ts";

test("direct ZIP preparation never claims item processing before extraction", () => {
  assert.equal(
    batchActivityCopy({
      status: "extracting",
      totalItems: 0,
      pendingItems: 0,
      processedItems: 0,
      concurrencyLimit: 10,
    }),
    "Preparing the uploaded ZIP and validating its CAD files",
  );
  assert.equal(
    batchActivityCopy({
      status: "pending",
      totalItems: 0,
      pendingItems: 0,
      processedItems: 0,
      concurrencyLimit: 10,
    }),
    "Waiting for secure ZIP preparation to start",
  );
});

test("queued and processing copy uses the real item and concurrency counts", () => {
  assert.equal(
    batchActivityCopy({
      status: "pending",
      totalItems: 3,
      pendingItems: 3,
      processedItems: 0,
      concurrencyLimit: 2,
    }),
    "3 items queued for analysis",
  );
  assert.equal(
    batchActivityCopy({
      status: "processing",
      totalItems: 3,
      pendingItems: 2,
      processedItems: 1,
      concurrencyLimit: 2,
    }),
    "Processing up to 2 items in parallel",
  );
});

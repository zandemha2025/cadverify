import assert from "node:assert/strict";
import test from "node:test";

import {
  acceptedBatchFromErrorPayload,
  analysisPageHref,
  batchProgressSettled,
  durableDesignFromErrorPayload,
} from "./recovery-records.ts";

test("accepted batch identity is retained only from a complete structured 503", () => {
  assert.deepEqual(
    acceptedBatchFromErrorPayload({
      detail: {
        accepted_batch: {
          batch_id: "01BATCHQUEUEFAILED00000001",
          status: "failed",
          status_url: "/api/v1/batch/01BATCHQUEUEFAILED00000001",
        },
      },
    }),
    {
      batch_id: "01BATCHQUEUEFAILED00000001",
      status: "failed",
      status_url: "/api/v1/batch/01BATCHQUEUEFAILED00000001",
    },
  );
  assert.equal(acceptedBatchFromErrorPayload({ detail: {} }), undefined);
  assert.equal(
    acceptedBatchFromErrorPayload({ detail: { accepted_batch: { batch_id: "partial" } } }),
    undefined,
  );
});

test("cancelled progress keeps polling until in-flight items become terminal", () => {
  assert.equal(batchProgressSettled("cancelled", 1), false);
  assert.equal(batchProgressSettled("cancelled", 0), true);
  assert.equal(batchProgressSettled("processing", 0), false);
  assert.equal(batchProgressSettled("completed", 0), true);
});

test("durable failed design is retained while malformed error bodies are ignored", () => {
  const design = durableDesignFromErrorPayload<{ id: string; status: string }>({
    design: { id: "01DESIGNQUEUEFAILED0000001", status: "failed" },
  });
  assert.deepEqual(design, { id: "01DESIGNQUEUEFAILED0000001", status: "failed" });
  assert.equal(durableDesignFromErrorPayload({ design: { status: "failed" } }), undefined);
});

test("batch analysis API URLs map to the matching human detail page", () => {
  assert.equal(
    analysisPageHref("/api/v1/analyses/01ANALYSIS000000000000001"),
    "/analyses/01ANALYSIS000000000000001",
  );
  assert.equal(analysisPageHref(null), null);
  assert.equal(analysisPageHref("/api/v1/cost-decisions/01COST"), null);
});

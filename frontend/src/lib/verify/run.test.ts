import { test } from "node:test";
import assert from "node:assert/strict";
import type { ValidationResult } from "@/lib/api";
import { isCurrentRun, validationAllowsCost } from "./run-gates.ts";

// Regression: QA ISSUE-001 — a validation-service interruption must stop before
// costing so the UI cannot turn an operational outage into a stale DFM verdict.
test("costing proceeds only after routing and DFM returns", () => {
  assert.equal(validationAllowsCost(null), false);
  assert.equal(
    validationAllowsCost({ best_process: "fdm" } as ValidationResult),
    true
  );
});

// Regression: QA ISSUE-004 — a slow guided sample cannot reopen itself after the
// user has gone back or started a newer own-CAD run.
test("only the latest guided run owns its completion", () => {
  assert.equal(isCurrentRun(4, 4), true);
  assert.equal(isCurrentRun(4, 5), false);
});

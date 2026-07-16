import { test } from "node:test";
import assert from "node:assert/strict";
import type { ValidationResult } from "@/lib/api";
import { validationAllowsCost } from "./run-gates.ts";

// Regression: QA ISSUE-001 — a validation-service interruption must stop before
// costing so the UI cannot turn an operational outage into a stale DFM verdict.
test("costing proceeds only after routing and DFM returns", () => {
  assert.equal(validationAllowsCost(null), false);
  assert.equal(
    validationAllowsCost({ best_process: "fdm" } as ValidationResult),
    true
  );
});

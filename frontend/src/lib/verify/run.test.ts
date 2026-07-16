import { test } from "node:test";
import assert from "node:assert/strict";
import type { ValidationResult } from "@/lib/api";
import {
  isCurrentRun,
  readJsonOrNull,
  validationAllowsCost,
} from "./run-gates.ts";

// Regression: QA ISSUE-001 — a validation-service interruption must stop before
// costing or context persistence, so it cannot create a verdict or saved mutation.
test("downstream work proceeds only after routing and DFM returns", () => {
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

// Regression: QA ISSUE-005 — unreadable cost JSON stays a recoverable cost-only
// failure instead of throwing through and erasing the validation result.
test("malformed cost JSON resolves to an isolated parse failure", async () => {
  const parsed = await readJsonOrNull({
    json: async () => {
      throw new SyntaxError("unexpected token");
    },
  });
  assert.equal(parsed, null);
});

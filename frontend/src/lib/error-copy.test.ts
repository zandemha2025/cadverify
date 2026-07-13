import { test } from "node:test";
import assert from "node:assert/strict";
import { distinctErrorDetail } from "./error-copy.ts";

test("removes a detail that only repeats the error title", () => {
  assert.equal(
    distinctErrorDetail("Cost decision not found", "Cost decision not found"),
    undefined,
  );
  assert.equal(
    distinctErrorDetail("Analysis not found", "  Analysis not found  "),
    undefined,
  );
});

test("preserves a distinct actionable detail", () => {
  assert.equal(
    distinctErrorDetail("Cost decision not found", "Check the link and try again."),
    "Check the link and try again.",
  );
});

test("omits empty detail text", () => {
  assert.equal(distinctErrorDetail("Something went wrong", "  "), undefined);
  assert.equal(distinctErrorDetail("Something went wrong"), undefined);
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { formatVolumeChange, repairFailureReason } from "./repair-details.ts";

test("a refused repair shows the reason the API actually sends", () => {
  // Shape returned when the engine output is not a watertight solid.
  assert.equal(
    repairFailureReason({
      tier: "pymeshfix",
      reason: "Repair did not produce a watertight positive-volume solid.",
      duration_ms: 812,
    }),
    "Repair did not produce a watertight positive-volume solid.",
  );
  // Timeout: str(TimeoutError()) is empty, so `reason` must win over `error`.
  assert.equal(
    repairFailureReason({ error: "", reason: "Repair timed out after 30 s." }),
    "Repair timed out after 30 s.",
  );
});

test("older error-only responses still explain, and blanks never render", () => {
  assert.equal(repairFailureReason({ error: "boom" }), "boom");
  assert.equal(repairFailureReason({ error: "  ", reason: "" }), null);
  assert.equal(repairFailureReason({}), null);
});

test("volume change is signed and withheld when unmeasured", () => {
  assert.equal(formatVolumeChange(10.4), "+10.4%");
  assert.equal(formatVolumeChange(-3.27), "-3.3%");
  assert.equal(formatVolumeChange(0), "0.0%");
  assert.equal(formatVolumeChange(-0.04), "0.0%");
  assert.equal(formatVolumeChange(null), null);
  assert.equal(formatVolumeChange(undefined), null);
  assert.equal(formatVolumeChange(Number.NaN), null);
});

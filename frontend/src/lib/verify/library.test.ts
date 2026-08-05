/**
 * Pure tests for the parts-master library readout (lib/verify/library) — run under
 * the repo's `node --test` type-stripping runner. No React, no fetch, no DB.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  readOnboardSummary,
  onboardReadout,
  hasOnboardOutcome,
  type OnboardSummary,
} from "./library.ts";

const CLEAN: OnboardSummary = {
  onboarded: 3,
  unnamed: 0,
  skipped: [],
  manifest_registered: 3,
  library_size: 3,
  mapping_errors: [],
};

test("readout: clean batch is 'Onboarded N · library now M'", () => {
  assert.equal(onboardReadout(CLEAN), "Onboarded 3 parts · library now 3");
});

test("readout: singular part reads 'part'", () => {
  assert.equal(onboardReadout({ ...CLEAN, onboarded: 1, library_size: 1 }), "Onboarded 1 part · library now 1");
});

test("readout: skips + unnamed are surfaced honestly, never hidden", () => {
  const s: OnboardSummary = {
    ...CLEAN,
    onboarded: 2,
    unnamed: 1,
    library_size: 5,
    skipped: [{ filename: "junk.stl", reason: "bad geometry" }],
  };
  assert.equal(onboardReadout(s), "Onboarded 2 parts · library now 5 (1 skipped · 1 unnamed)");
});

test("readOnboardSummary: coerces a real body and rejects a non-summary", () => {
  const parsed = readOnboardSummary({ onboarded: 2, library_size: 4 });
  assert.ok(parsed);
  assert.equal(parsed?.onboarded, 2);
  assert.equal(parsed?.library_size, 4);
  assert.equal(parsed?.skipped.length, 0);
  assert.equal(readOnboardSummary(null), null);
  assert.equal(readOnboardSummary({ nope: true }), null);
});

test("hasOnboardOutcome: true on work OR skips, false on an empty no-op", () => {
  assert.equal(hasOnboardOutcome(CLEAN), true);
  assert.equal(hasOnboardOutcome({ ...CLEAN, onboarded: 0 }), false);
  assert.equal(
    hasOnboardOutcome({ ...CLEAN, onboarded: 0, skipped: [{ filename: "x", reason: "y" }] }),
    true
  );
});

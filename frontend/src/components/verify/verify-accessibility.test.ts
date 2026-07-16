import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const screenSource = await readFile(new URL("./verify-screen.tsx", import.meta.url), "utf8");

// Regression: design FINDING-001 — keyboard and screen-reader order must match
// the value-first visual order, and assumption selectors expose their state.
test("Verify presents the result before optional assumptions accessibly", () => {
  const walk = screenSource.indexOf("{/* the walk */}");
  const personalization = screenSource.indexOf("<PersonalizationDoor", walk);
  assert.ok(walk >= 0 && personalization > walk);
  assert.match(screenSource, /aria-pressed=\{on\}/);
  assert.match(screenSource, /role="radiogroup"/);
  assert.match(screenSource, /aria-checked=\{on\}/);
});

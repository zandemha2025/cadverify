import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const screenSource = await readFile(new URL("./verify-screen.tsx", import.meta.url), "utf8");
const appSource = await readFile(new URL("./verify-app.tsx", import.meta.url), "utf8");

// Regression: audit — "Repair & re-upload →" called onReverify, which re-runs
// runVerify on the same broken bytes: nothing was repaired and the deterministic
// geometry gate could only stop the walk again.
test("the geometry-gate action asks for a repaired file instead of resubmitting", () => {
  const gate = screenSource.indexOf("THE WALK STOPS AT THE FAILED GATE");
  const end = screenSource.indexOf("{/* downstream steps only when the engine got past the gate */}", gate);
  assert.ok(gate >= 0 && end > gate);
  const block = screenSource.slice(gate, end);
  assert.match(block, /<GhostButton onClick=\{onPickFile\}>Upload a repaired file →<\/GhostButton>/);
  assert.doesNotMatch(block, /onReverify/);
  assert.doesNotMatch(screenSource, /Repair &amp; re-upload/);
  // onPickFile opens the picker for a new file; it never re-runs the current one.
  assert.match(appSource, /onPickFile=\{pickOwnFile\}/);
  assert.match(appSource, /const pickOwnFile = useCallback\(\(\) => \{[^}]*fileRef\.current\?\.click\(\);\s*\}/);
});

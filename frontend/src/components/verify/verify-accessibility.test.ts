import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const screenSource = await readFile(new URL("./verify-screen.tsx", import.meta.url), "utf8");
const appSource = await readFile(new URL("./verify-app.tsx", import.meta.url), "utf8");

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

// Regression: QA ISSUE-005 — the in-flight state must win over the provisional
// result object, which cannot yet know which conditions the record holds.
test("service-condition copy stays pending while verification is running", () => {
  const status = screenSource.indexOf("function envDoorStatus");
  const pending = screenSource.indexOf("if (running)", status);
  const declared = screenSource.indexOf("if (result.envDeclared)", status);
  assert.ok(status >= 0 && pending > status && declared > pending);
});

// Regression: Verify erased stored service conditions. Conditions are edited only
// in the editor, saved explicitly, and a change never re-runs verification by itself.
test("service conditions are an explicit edit, not a run side effect", () => {
  assert.match(screenSource, /<ServiceConditionsEditor/);
  assert.match(screenSource, /Save conditions/);
  assert.doesNotMatch(appSource, /\}, \[env\]\);/);
  assert.match(appSource, /saveServiceConditions\(meshHash, next,/);
});

// Regression: QA ISSUE-007 — material value/provenance follows the cost record;
// selecting the API's undeclared polymer default is never mislabeled USER.
test("material provenance follows the engine contract", () => {
  assert.match(screenSource, /assumption\.name === "material_class"/);
  assert.match(screenSource, /normProv\(materialAssumption\.provenance\)/);
  assert.match(appSource, /setMaterialTouched\(next !== "polymer"\)/);
});

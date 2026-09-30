import assert from "node:assert/strict";

export async function assertFitInputsReady(page) {
  assert.equal(await page.playwright.getByRole("button", { name: "Check fit in context", exact: true }).isEnabled(), true,
    "Changing fit inputs must allow a new check, even while an older request completes");
  assert.equal(await page.playwright.getByTestId("context-fit-results").isVisible(), false,
    "Previous inputs' measurements must stay withheld");
  return { status: "PASS", nextCheckEnabled: true, oldResultWithheld: true };
}

export async function assertFitGap(page, gapMm) {
  const results = page.playwright.getByTestId("context-fit-results");
  await results.waitFor({ state: "visible", timeoutMs: 20000 });
  const text = await results.innerText();
  assert.ok(text.includes("No measured overlap."), text);
  assert.ok(text.includes(`${gapMm.toFixed(3)} mm · MEASURED`), text);
  return { status: "PASS", measuredGapMm: gapMm, noOverlap: true };
}

export async function assertFitOverlap(page, volumeMm3) {
  const text = await page.playwright.getByTestId("context-fit-results").innerText();
  assert.ok(text.includes(`${volumeMm3.toFixed(3)} mm³ measured overlap.`), text);
  assert.ok(text.includes("0.000 mm - the parts overlap."), text);
  return { status: "PASS", measuredOverlapMm3: volumeMm3, zeroClearance: true };
}

export async function assertFitPreview(page) {
  assert.equal(await page.playwright.getByTestId("context-fit-panel").locator("canvas").isVisible(), true,
    "The submitted STEP/STL pair must have a visible geometry canvas");
  return { status: "PASS", pairCanvasVisible: true };
}

export async function assertFitOffset(page, axis, expected) {
  const values = await page.playwright.getByTestId("context-fit-panel").locator('input[type="number"]').evaluateAll(
    inputs => inputs.map(input => ({ label: input.getAttribute("aria-label"), value: input.value, invalid: input.getAttribute("aria-invalid") })),
  );
  const field = values.find(input => input.label === `${axis} nudge mm`);
  assert.ok(field);
  assert.equal(field.value, expected);
  const valid = expected.trim() !== "" && Number.isFinite(Number(expected));
  assert.equal(field.invalid, String(!valid));
  assert.equal(await page.playwright.getByRole("button", { name: "Check fit in context", exact: true }).isEnabled(), valid);
  assert.equal(await page.playwright.getByTestId("context-fit-results").isVisible(), false);
  return { status: "PASS", axis, value: expected, canCheck: valid, previousResultsWithheld: true };
}

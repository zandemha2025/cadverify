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

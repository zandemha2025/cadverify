import assert from "node:assert/strict";

// Run through the native browser after a controlled local service failure.
export async function assertDesignHistoryFailure(page) {
  const snapshot = await page.playwright.domSnapshot();
  assert.match(snapshot, /Could not load revision history/);
  assert.equal(await page.playwright.getByRole("button", { name: "Try again", exact: true }).isEnabled(), true);
  assert.equal(await page.playwright.locator("[data-revision-history-state]").getAttribute("data-revision-history-state"), "error");
}

export async function assertDesignListFailure(page) {
  const snapshot = await page.playwright.domSnapshot();
  assert.match(snapshot, /Could not load designs/);
  assert.doesNotMatch(snapshot, /No designs yet/);
  assert.equal(await page.playwright.getByRole("button", { name: "Try again", exact: true }).isEnabled(), true);
}

export async function assertDesignComparisonIdle(page, designName) {
  assert.equal(await page.playwright.getByRole("heading", { name: designName, exact: true }).isVisible(), true);
  const snapshot = await page.playwright.getByTestId("design-version-diff").innerText();
  assert.doesNotMatch(snapshot, /BEFORE|AFTER|Plan changes|Generated geometry changes|outage/);
  assert.equal(await page.playwright.getByRole("button", { name: "Compare", exact: true }).isEnabled(), true);
}

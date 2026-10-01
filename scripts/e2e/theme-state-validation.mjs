// Import from cua_repl after a native theme action; no standalone browser driver.
import assert from "node:assert/strict";

export async function assertThemeControl(page, expectedDark) {
  const state = await page.playwright.evaluate(() => ({
    dark: document.documentElement.classList.contains("dark"),
    labels: Array.from(document.querySelectorAll('button[aria-label*="theme"]'))
      .map((button) => button.getAttribute("aria-label")),
  }));
  assert.equal(state.dark, expectedDark);
  assert.ok(state.labels.length > 0, "theme control is present");
  for (const label of state.labels) {
    assert.equal(label, expectedDark ? "Switch to light theme" : "Switch to dark theme");
  }
  return state;
}

// Import from cua_repl after closing the native command palette.
import assert from "node:assert/strict";

export async function assertPaletteReturnFocus(page, expectedLabel) {
  const state = await page.playwright.evaluate(() => ({
    tag: document.activeElement?.tagName,
    label: document.activeElement?.getAttribute("aria-label"),
    text: document.activeElement?.textContent?.trim(),
    dialogOpen: !!document.querySelector('[role="dialog"]'),
  }));
  assert.equal(state.dialogOpen, false);
  assert.equal(state.label || state.text, expectedLabel);
  return state;
}

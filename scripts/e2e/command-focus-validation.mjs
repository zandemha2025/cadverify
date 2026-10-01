// Import from cua_repl after closing the native command palette and observing
// the settled UI (Radix restores focus after the dialog unmounts).
import assert from "node:assert/strict";

export async function assertPaletteReturnFocus(page, expectedLabel, expectedHeading) {
  const state = await page.playwright.evaluate(() => ({
    tag: document.activeElement?.tagName,
    label: document.activeElement?.getAttribute("aria-label"),
    text: document.activeElement?.textContent?.trim().slice(0, 160),
    dialogOpen: !!document.querySelector('[role="dialog"]'),
  }));
  assert.equal(state.dialogOpen, false);
  assert.equal(state.label || state.text, expectedLabel);
  if (expectedHeading) {
    assert.equal(await page.playwright.getByRole("heading", { name: expectedHeading, exact: true }).isVisible(), true);
  }
  return state;
}

export async function assertSingleVerifyPalette(page) {
  assert.equal(await page.playwright.getByRole("dialog", { name: "Command palette", exact: true }).count(), 0);
  assert.equal(await page.playwright.getByRole("dialog", { name: "Verify command palette", exact: true }).isVisible(), true);
  const focused = await page.playwright.evaluate(() => document.activeElement?.getAttribute("aria-label"));
  assert.equal(focused, "Command palette search");
}

export async function assertShortcutsCommandSelected(page, expectedHeading) {
  await assertShortcutsModal(page);
  assert.equal(await page.playwright.evaluate(() => document.querySelector("main h1")?.textContent), expectedHeading);
}

export async function assertShortcutsModal(page) {
  const state = await page.playwright.evaluate(() => {
    const dialog = document.querySelector('[role="dialog"]');
    return {
      dialogCount: document.querySelectorAll('[role="dialog"]').length,
      backgroundHidden: !!document.querySelector("main")?.closest('[aria-hidden="true"]'),
      focusInside: !!dialog?.contains(document.activeElement),
      focusedLabel: document.activeElement?.getAttribute("aria-label"),
    };
  });
  assert.equal(state.dialogCount, 1);
  assert.equal(state.backgroundHidden, true);
  assert.equal(state.focusInside, true);
  assert.equal(state.focusedLabel, "Close keyboard shortcuts");
  return state;
}

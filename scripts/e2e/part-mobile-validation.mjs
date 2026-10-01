import assert from "node:assert/strict";

// Invoke through CUA with a real part standing open at the requested viewport.
export async function assertPartStandingFits(page) {
  const state = await page.playwright.evaluate(() => {
    const panel = [...document.querySelectorAll("main")].find((el) =>
      [...el.children].some((child) => child.tagName === "BUTTON" && child.textContent.trim() === "← PARTS"));
    if (!panel) return null;
    const controls = [...panel.querySelectorAll("button")].filter((el) =>
      ["Re-verify", "Compare", "open program →", "open record →", "hide record"].includes(el.textContent.trim()));
    return {
      width: panel.clientWidth, scrollWidth: panel.scrollWidth, viewport: innerWidth,
      controls: controls.map((el) => ({ text: el.textContent.trim(),
        left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right })),
    };
  });
  assert.ok(state, "A real part standing must be open");
  assert.ok(state.scrollWidth <= state.width + 1, JSON.stringify(state));
  assert.ok(state.controls.some((control) => /record/.test(control.text)), "A saved record control must be present");
  for (const control of state.controls) {
    assert.ok(control.left >= 0 && control.right <= state.viewport + 1, JSON.stringify(control));
  }
  return { status: "PASS", ...state };
}

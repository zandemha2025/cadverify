import assert from "node:assert/strict";

export async function assertComparisonFits(page, expectedViewport) {
  const state = await page.playwright.evaluate(() => {
    const panel = [...document.querySelectorAll("main")].find((el) =>
      [...el.children].some((child) => child.tagName === "H1" && child.textContent === "Compare"));
    return panel ? { viewport: innerWidth, width: panel.clientWidth, scroll: panel.scrollWidth,
      controls: [...panel.querySelectorAll("select,input,button")].map((el) => ({
        left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right,
      })) } : null;
  });
  assert.ok(state, "Comparison must be open");
  assert.equal(state.viewport, expectedViewport, "The intended viewport must actually be active");
  assert.ok(state.scroll <= state.width + 1, JSON.stringify(state));
  assert.ok(state.controls.every((el) => el.left >= 0 && el.right <= state.viewport + 1), JSON.stringify(state.controls));
  return { status: "PASS", ...state };
}

export async function assertSelectedComparisonRecord(page, recordId) {
  const selected = await page.playwright.evaluate(() => {
    const select = [...document.querySelectorAll("select")].find((el) =>
      el.closest("label")?.textContent.trim().startsWith("A"));
    return select?.value;
  });
  assert.equal(selected, recordId, "Part Compare must retain the selected saved record");
  return { status: "PASS", recordId };
}

// CUA assertion; expected values come from the native saved-report export.
export async function assertComparedRoute(page, { quantity, process, makePrice, toolPrice }) {
  const text = await page.playwright.locator("section").filter({ hasText: "ROUTE VS ROUTE" }).innerText();
  assert.ok(text.includes(`qty ${quantity} —`), `Missing computed quantity ${quantity}`);
  assert.ok(text.includes(`${process} (make-now)`), `Wrong quantity-specific process: ${text}`);
  assert.ok(text.includes(`make ${makePrice} `), `Wrong quantity-specific make price: ${text}`);
  assert.ok(text.includes(`acquire ${toolPrice} `), `Wrong tooling price: ${text}`);
  assert.ok(text.includes("requires redesign"), "Conditional tooling must retain its redesign requirement");
  return { status: "PASS", quantity, process, makePrice, toolPrice, text };
}

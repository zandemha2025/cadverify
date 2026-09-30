import assert from "node:assert/strict";

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

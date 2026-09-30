import assert from "node:assert/strict";

// Run with the CUA tab. Expected prices come from the saved report's quantity table.
export async function assertVerifyResource(page, { quantity, process, price }) {
  const card = await page.playwright.evaluate((process) => {
    const title = [...document.querySelectorAll("p")].find((el) =>
      el.textContent.startsWith(`${process} —`) && /MAKE NOW|OWNED → MARGINAL/.test(el.textContent));
    return title?.parentElement.innerText ?? null;
  }, process);
  assert.ok(card, `No recommendation card for ${process}`);
  assert.ok(card.includes(`${price} /unit at this qty`), card);
  assert.ok(card.includes(`computed qty ${quantity}`), card);
  return { status: "PASS", quantity, process, price, card };
}

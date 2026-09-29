import assert from "node:assert/strict";

// Run with a CUA tab on /batch in the disposable local audit workspace.
export async function verifyBatchConcurrencyBoundary(tab) {
  const input = tab.playwright.getByRole("spinbutton", { name: "Concurrency limit" });
  assert.equal(await input.getAttribute("min"), "1");
  assert.equal(await input.getAttribute("max"), "12");
  await input.fill("13");
  assert.equal(await input.evaluate((el) => el.value), "12");
  await input.fill("-1");
  assert.equal(await input.evaluate((el) => el.value), "1");
  await input.fill("2");
  assert.equal(await input.evaluate((el) => el.value), "2");
  return { status: "PASS", checks: ["supported range 1–12", "upper/lower bounds", "valid value retained"] };
}

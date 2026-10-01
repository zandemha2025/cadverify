import assert from "node:assert/strict";

// Run through CUA on the real STEP workspace, with default quantities and
// the input panel expanded. Draft edits must not relabel an older calculation.
export async function verifyCostScenarioSnapshot(tab) {
  await tab.playwright.getByRole("textbox", { name: "Quantities (comma list, up to 6)" }).fill("123");
  await tab.playwright.getByRole("tab", { name: "Glass Box", exact: true }).click();
  await tab.playwright.getByRole("button", { name: "Save as scenario", exact: true }).click();
  const scenario = tab.playwright.getByRole("button", { name: "Generic · qty 50 $3.80", exact: true });
  assert.equal(await scenario.count(), 1, "Save the currently displayed result");
  await scenario.click();
  await tab.playwright.getByRole("button", { name: "Save as scenario", exact: true }).waitFor({ state: "visible", timeoutMs: 10000 });
  const quantities = await tab.playwright.getByRole("group", { name: "Qty", exact: true }).innerText();
  assert.ok(quantities.includes("50") && quantities.includes("5,000") && !quantities.includes("123"), quantities);
  return { status: "PASS", draftQuantity: 123, savedAndRecalledQuantities: [50, 5000], savedUnitCost: 3.80 };
}

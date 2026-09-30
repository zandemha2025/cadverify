import assert from "node:assert/strict";

// Run against the actual import result in a CUA-controlled tab.
export async function assertLibraryOutcome(page, expectedReadout, reasons) {
  const snapshot = await page.playwright.domSnapshot();
  assert.equal(await page.playwright.getByText(expectedReadout, { exact: true }).count(), 1,
    `Incorrect import count: ${expectedReadout}`);
  const issues = await page.playwright.getByRole("list", { name: "Mapping issues" }).innerText();
  for (const reason of reasons) assert.ok(issues.includes(reason), `Hidden mapping reason: ${reason}`);
  assert.ok(!snapshot.includes("see reasons"), "Never point to nonexistent error details");
  assert.equal(await page.playwright.getByRole("button", { name: "Onboard library", exact: true }).isEnabled(), false);
  assert.equal(await page.playwright.getByRole("button", { name: "Choose CAD files…", exact: true }).count(), 1);
  assert.equal(await page.playwright.getByRole("button", { name: "Identity mapping (optional)…", exact: true }).count(), 1);
  return { status: "PASS", readout: expectedReadout, issues };
}

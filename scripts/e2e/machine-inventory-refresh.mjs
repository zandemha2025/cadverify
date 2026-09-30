import assert from "node:assert/strict";

// CUA: a real 10 mm cube is already loaded; edit the synthetic audit machine.
export async function changeMachineEnvelopeAndVerify(tab, x, expectedTitle) {
  await tab.playwright.getByRole("button", { name: "Your machines", exact: true }).click();
  await tab.playwright.getByRole("button", { name: /^Audit local FDM 046 OWNED/ }).click();
  await tab.playwright.getByRole("button", { name: "Edit specs", exact: true }).click();
  await tab.playwright.getByRole("textbox", { name: "ENVELOPE X (mm)", exact: true }).fill(String(x));
  await tab.playwright.getByRole("button", { name: "Save changes", exact: true }).click();
  await tab.playwright.getByRole("button", { name: "Verify", exact: true }).click();
  await tab.playwright.getByText(expectedTitle, { exact: true }).waitFor({ state: "visible", timeoutMs: 15000 });
  assert.equal(await tab.playwright.getByText(`${x} × 200 × 200 mm`, { exact: true }).count(), 1);
  return { status: "PASS", envelopeX: x, verdict: expectedTitle, reuploadedFile: false };
}

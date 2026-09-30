import assert from "node:assert/strict";

// Run through CUA on the uploaded cube-10mm.stl after a draft unit edit,
// an explicit inch re-cost, and recalling the saved millimetre scenario.
export async function verifyUnitGeometryAgreement(tab, sizeMm) {
  await tab.playwright.getByRole("tab", { name: "Routing & DFM", exact: true }).click();
  await tab.playwright.locator('[data-preview-state="ready"]').waitFor({ state: "visible", timeoutMs: 10000 });
  const dimensions = `${sizeMm} × ${sizeMm} × ${sizeMm} mm`;
  assert.equal(await tab.playwright.getByText(dimensions, { exact: true }).count(), 2,
    "Cost and DFM must show the same submitted dimensions");
  assert.equal(await tab.playwright.locator("[data-preview-face-space]").getAttribute("data-preview-face-space"), "analysis",
    "Preview must retain exact alignment with the submitted DFM mesh");
  const clear = tab.playwright.getByRole("button", { name: "Clear selected issue", exact: true });
  if (await clear.count()) await clear.click();
  await tab.playwright.getByRole("button", {
    name: "8 sidewall faces (100.0% of sidewall area) below 1.0° draft for injection_molding.", exact: true,
  }).click();
  await tab.playwright.getByTestId("pinpoint-issue-card").waitFor({ state: "visible", timeoutMs: 5000 });
  assert.equal(await tab.playwright.getByText("The part preview is available. Exact face highlighting is unavailable for this converted mesh; use the finding details below.", { exact: true }).count(), 0);
  return { status: "PASS", costAndDfmDimensionsMm: [sizeMm, sizeMm, sizeMm], previewFaceSpace: "analysis" };
}

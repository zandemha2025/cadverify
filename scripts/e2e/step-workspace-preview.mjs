import assert from "node:assert/strict";

// PROD-022. Accepts a CUA tab on the authenticated, empty Analyze/Cost workspace.
// Use a real STEP file; a rendered canvas alone is insufficient without the
// viewer's ready signal, which is emitted only after parsing actual geometry.
export async function verifyStepWorkspacePreview(tab, stepPath) {
  const page = tab.playwright;
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: /Drag and drop or click to upload/ }).click();
  await (await chooser).setFiles([stepPath]);
  await page.getByRole("button", { name: "New part", exact: true }).waitFor({ state: "visible" });
  await page.getByLabel("Interactive 3D preview ready", { exact: true }).waitFor({ state: "visible", timeoutMs: 60000 });
  await page.getByRole("heading", { name: "Manufacturability issues", exact: true }).waitFor({ state: "visible", timeoutMs: 60000 });
  const viewer = page.getByLabel("Interactive 3D preview ready", { exact: true });
  assert.equal(await viewer.locator("canvas").count(), 1);
  assert.equal(await viewer.getAttribute("data-preview-face-space"), "analysis");
  assert.equal(await page.getByText("STEP preview requires backend conversion", { exact: true }).count(), 0);
  return { status: "PASS", checks: ["real STEP upload", "converted geometry parsed", "interactive preview ready", "analysis-aligned face indices"] };
}

// For backend/tests/assets/cube.step: its vertical walls require draft for
// molding. Selecting that measured finding must render its actual face overlay.
export async function verifyStepDraftHighlight(tab) {
  const page = tab.playwright;
  const clear = page.getByRole("button", { name: "Clear selected issue", exact: true });
  if (await clear.count()) await clear.click();
  await page.getByRole("button", { name: /Required INSUFFICIENT_DRAFT locate/ }).click();
  await page.getByTestId("pinpoint-issue-card").waitFor({ state: "visible" });
  assert.match(await page.getByTestId("pinpoint-issue-card").innerText(), /INSUFFICIENT_DRAFT/);
  assert.equal(await page.getByText(/Exact face highlighting is unavailable/).count(), 0);
  return { status: "PASS", checks: ["draft finding selects", "finding details visible", "matching mesh fingerprint enables highlights"] };
}

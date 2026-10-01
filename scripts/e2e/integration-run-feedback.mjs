import assert from "node:assert/strict";

// Regression PROD-018/019. Run against an authenticated disposable workspace
// on /integrations. Accepts a CUA tab; every interaction uses its browser API.
// partialCsv has one valid row and a blank part_id on line 3; validCsv has one
// valid row. All runs below are dry runs and do not import business records.
export async function verifyVendorApiSeparation(tab) {
  const page = tab.playwright;
  const connector = page.getByRole("combobox", { name: "Connector", exact: true });
  const run = page.getByRole("button", { name: "Run", exact: true });
  for (const label of ["SAP S/4HANA Product/BOM read-only", "PTC Windchill Part/BOM read-only"]) {
    await connector.selectOption({ label });
    const status = await page.getByRole("status").innerText();
    assert.match(status, label.startsWith("SAP") ? /preview a SAP BOM explosion/ : /preview and import a Windchill BOM/);
    if (label.startsWith("SAP")) {
      assert.match(status, /Assembly import is not supported/);
      assert.doesNotMatch(await page.getByRole("main").innerText(), /SAP BOM reads and API imports are not available yet/);
    }
    assert.equal(await run.count(), 0, "vendor API must not route through CSV");
  }
}

export async function verifyIntegrationFeedback(tab, { partialCsv, validCsv }) {
  const page = tab.playwright;
  const connector = page.getByRole("combobox", { name: "Connector", exact: true });
  const run = page.getByRole("button", { name: "Run", exact: true });
  await verifyVendorApiSeparation(tab);
  await connector.selectOption({ label: "SAP manifest CSV" });
  assert.equal(await page.getByRole("link", { name: "Download CSV template" }).getAttribute("href"),
    "/api/proxy/manifest/import/template");
  await page.getByRole("combobox", { name: "Mode", exact: true }).selectOption("dry_run");

  async function upload(path) {
    const pending = page.waitForEvent("filechooser");
    await page.getByLabel("CSV", { exact: true }).click();
    await (await pending).setFiles([path]);
    assert.equal(await run.isEnabled(), true);
    await run.click();
  }

  await upload(partialCsv);
  await page.getByText(/Line 3:.*missing part_id/).first().waitFor({ state: "visible" });
  assert.match(await page.getByRole("main").innerText(), /Dry-run only\. No data imported\./);
  assert.equal(await run.isEnabled(), false);
  assert.equal(await page.getByLabel("CSV", { exact: true }).evaluate((el) => el.value), "");

  await upload(validCsv);
  await page.getByText("Dry-run passed. No data imported.", { exact: true }).waitFor({ state: "visible" });
  assert.match(await page.getByRole("table").innerText(), /1\/1 valid/);
  assert.equal(await run.isEnabled(), false);

  await tab.reload();
  await page.getByText(/Line 3:.*missing part_id/).first().waitFor({ state: "visible" });
  assert.match(await page.getByRole("table").innerText(), /1\/1 valid/);
  return { status: "PASS", checks: ["vendor API/CSV separation", "template URL", "partial row error", "file reset", "corrected CSV retry", "persisted run details"] };
}

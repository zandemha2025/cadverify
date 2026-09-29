import assert from "node:assert/strict";

// Run only in an authenticated, disposable local admin workspace via a CUA tab.
// These sentinels grant no access; private egress must be rejected before HTTP.
export async function verifyConnectorCredentialFeedback(tab, suffix) {
  const page = tab.playwright;
  const names = [];
  for (const connectorId of ["sap_s4hana_product_bom_readonly", "windchill_part_bom_readonly"]) {
    await page.getByRole("combobox", { name: "Connector", exact: true }).selectOption(connectorId);
    const panel = page.getByRole("region", { name: "Vendor connection settings" });
    const name = `QA blocked endpoint ${connectorId.startsWith("sap_") ? "SAP" : "Windchill"} ${suffix}`;
    await panel.getByLabel("Connection name", { exact: true }).fill(name);
    await panel.getByLabel("Service URL", { exact: true }).fill("https://127.0.0.1");
    const auth = panel.getByRole("combobox", { name: "Authentication", exact: true });
    await auth.selectOption("oauth2_client_credentials");
    assert.equal(await panel.getByLabel("Client secret", { exact: true }).getAttribute("type"), "password");
    assert.equal(await panel.getByLabel("Token endpoint URL", { exact: true }).count(), 1);
    await auth.selectOption("api_key");
    assert.equal(await panel.getByLabel("API key", { exact: true }).getAttribute("type"), "password");
    await auth.selectOption("basic");
    assert.equal(await panel.getByLabel("Password", { exact: true }).getAttribute("type"), "password");
    await auth.selectOption("bearer");
    const token = panel.getByLabel("Access token", { exact: true });
    assert.equal(await token.getAttribute("type"), "password");
    await token.fill("qa-nonfunctional-sentinel");
    await panel.getByRole("button", { name: "Save connection", exact: true }).click();
    await panel.getByText("Connection saved. Use Test connection to check access.", { exact: true }).waitFor({ state: "visible" });
    const saved = panel.getByRole("article", { name, exact: true });
    await saved.waitFor({ state: "visible" });
    assert.equal(await token.evaluate((el) => el.value === ""), true, "clear secret after save");
    assert.doesNotMatch(await saved.innerText(), /qa-nonfunctional-sentinel/);
    assert.doesNotMatch(await saved.innerText(), /succeeded/);
    await saved.getByRole("button", { name: "Test connection", exact: true }).click();
    await saved.getByRole("alert").waitFor({ state: "visible" });
    assert.match(await saved.getByRole("alert").innerText(), /must resolve to public addresses/);
    assert.equal(await saved.getByRole("button", { name: "Test connection", exact: true }).isEnabled(), true);
    names.push({ connectorId, name });
  }
  return { status: "PASS", profiles: names, checks: ["four authentication forms", "encrypted save flow", "secret field cleared", "saved is not connected", "private egress blocked", "actionable failure and retry"] };
}

export async function verifyConnectorCredentialRevocation(tab, profiles) {
  const page = tab.playwright;
  await tab.reload();
  for (const { connectorId, name } of profiles) {
    await page.getByRole("combobox", { name: "Connector", exact: true }).selectOption(connectorId);
    const saved = page.getByRole("article", { name, exact: true });
    await saved.waitFor({ state: "visible" });
    await saved.getByRole("button", { name: "Revoke connection", exact: true }).click();
    await saved.getByText("Revoked", { exact: true }).waitFor({ state: "visible" });
    assert.equal(await saved.getByRole("button").count(), 0);
  }
  await tab.reload();
  for (const { connectorId, name } of profiles) {
    await page.getByRole("combobox", { name: "Connector", exact: true }).selectOption(connectorId);
    const saved = page.getByRole("article", { name, exact: true });
    await saved.getByText("Revoked", { exact: true }).waitFor({ state: "visible" });
    assert.equal(await saved.getByRole("button").count(), 0);
  }
  return { status: "PASS", checks: ["saved profiles survive reload", "revoke prevents further probes", "revocation survives reload"] };
}

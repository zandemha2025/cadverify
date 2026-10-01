import assert from "node:assert/strict";

// Native CUA check. Inject a GET failure at the local backend boundary before
// loading the page, then remove it before calling the recovery check.
export async function assertOrganizationReadFailure(tab, { access = false, href = "/settings/organization" } = {}) {
  const page = tab.playwright;
  const text = await page.getByRole("main").innerText();
  assert.match(text, access ? /Organization access is unavailable/ : /Organization settings are unavailable/);
  assert.doesNotMatch(text, /Admins only|No members|No SAML group mappings|No invitations/);
  assert.equal(await page.getByRole("link", { name: "Try again", exact: true }).getAttribute("href"), href);
  for (const name of ["Send invite", "Add mapping", "Save connection"]) {
    assert.equal(await page.getByRole("button", { name, exact: true }).count(), 0);
  }
}

export async function retryOrganizationRead(tab, { integrations = false } = {}) {
  const page = tab.playwright;
  await page.getByRole("link", { name: "Try again", exact: true }).click();
  await page.getByRole("heading", { name: integrations ? "Integration runs" : "Members", exact: true }).waitFor({ state: "visible" });
  assert.doesNotMatch(await page.getByRole("main").innerText(), /Organization (?:access|settings) (?:is|are) unavailable/);
  if (!integrations) {
    assert.equal(await page.getByRole("button", { name: "Send invite", exact: true }).isEnabled(), true);
  }
}
